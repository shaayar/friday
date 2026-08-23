"""Tests for Phase 4 M5 conversation compactor orchestration + triggers."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from pathlib import Path

import pytest

from friday.compaction.compactor import CompactionResult, ConversationCompactor
from friday.compaction.exceptions import (
    CompactionAlreadyExistsError,
    CompactionCorruptError,
    CompactionOutputError,
    CompactionProviderError,
)
from friday.compaction.extractor import ConversationCompactionExtractor
from friday.compaction.models import ConversationCompaction
from friday.compaction.sqlite_store import SQLiteCompactionStore
from friday.memory.sqlite_store import SQLiteConversationStore


@dataclass(frozen=True, slots=True)
class Msg:
    id: int
    role: str = "user"
    content: str = "Message content."


def messages(*ids: int, content: str = "Message content.") -> tuple[Msg, ...]:
    return tuple(Msg(message_id, content=content) for message_id in ids)


class FakeLLM:
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self._response


EMPTY_JSON = """{
  "summary": "Conversation summary.",
  "facts": [],
  "decisions": [],
  "changes": [],
  "open_questions": []
}"""


class RaisingExtractor:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    async def extract(self, messages, *, conversation_id):
        self.calls += 1
        raise self._error


class StubExtractor:
    def __init__(self, compaction: ConversationCompaction) -> None:
        self._compaction = compaction
        self.calls = 0

    async def extract(self, messages, *, conversation_id):
        self.calls += 1
        return self._compaction


class FakeStore:
    """Minimal in-memory CompactionStorage faithful to M4's contract."""

    def __init__(self) -> None:
        self._data: dict[str, ConversationCompaction] = {}
        self._by_conversation: dict[int, list[str]] = {}
        self._hidden: dict[str, ConversationCompaction] = {}
        self.saved: list[ConversationCompaction] = []
        self.fail_save: Exception | None = None

    def preseed_hidden(self, compaction: ConversationCompaction) -> None:
        """Seed a compaction that `get` returns but list/save cannot see.

        Simulates a concurrent duplicate: the row already exists in storage
        while our boundary read was stale.
        """
        self._hidden[compaction.compaction_id] = compaction

    def list_for_conversation(
        self, conversation_id: int
    ) -> list[ConversationCompaction]:
        return [
            self._data[cid] for cid in self._by_conversation.get(conversation_id, [])
        ]

    def get(self, compaction_id: str) -> ConversationCompaction | None:
        return self._data.get(compaction_id) or self._hidden.get(compaction_id)

    def save(self, compaction: ConversationCompaction) -> ConversationCompaction:
        if self.fail_save is not None:
            raise self.fail_save
        if (
            compaction.compaction_id in self._data
            or compaction.compaction_id in self._hidden
        ):
            raise CompactionAlreadyExistsError(
                f"Compaction with ID {compaction.compaction_id} already exists"
            )
        self._data[compaction.compaction_id] = compaction
        self._by_conversation.setdefault(compaction.conversation_id, []).append(
            compaction.compaction_id
        )
        self.saved.append(compaction)
        return compaction


def make_compaction(
    *,
    compaction_id: str,
    conversation_id: int,
    first_message_id: int,
    last_message_id: int,
) -> ConversationCompaction:
    return ConversationCompaction(
        compaction_id=compaction_id,
        conversation_id=conversation_id,
        first_message_id=first_message_id,
        last_message_id=last_message_id,
        summary="Summary.",
    )


def make_compactor(
    store,
    *,
    message: int = 20,
    window: int = 20,
    size: int | None = None,
    llm_response: str = EMPTY_JSON,
    compaction_version: int = 1,
):
    llm = FakeLLM(llm_response)
    extractor = ConversationCompactionExtractor(
        llm, compaction_version=compaction_version
    )
    compactor = ConversationCompactor(
        store,
        extractor,
        message_threshold=message,
        max_window=window,
        unit_threshold=size,
    )
    return compactor, llm


def run_compact(compactor, messages, **kwargs) -> CompactionResult:
    """Run the (now async) compactor synchronously in the test's fresh loop."""
    return asyncio.run(compactor.compact(messages, **kwargs))


class TestNormalTrigger:
    def test_below_threshold_no_compaction(self) -> None:
        store = FakeStore()
        compactor, llm = make_compactor(store, message=20)
        result = run_compact(compactor, messages(*range(1, 20)), conversation_id=1)
        assert result == CompactionResult(
            compacted=False, compaction=None, remaining_messages=19
        )
        assert llm.calls == 0
        assert store.saved == []

    def test_at_threshold_compacts(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20)
        result = run_compact(compactor, messages(*range(1, 21)), conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert result.compaction.first_message_id == 1
        assert result.compaction.last_message_id == 20

    def test_above_threshold_compacts_one_bounded_window(self) -> None:
        store = FakeStore()
        compactor, llm = make_compactor(store, message=20, window=20)
        result = run_compact(compactor, messages(*range(1, 22)), conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert (
            result.compaction.first_message_id,
            result.compaction.last_message_id,
        ) == (1, 20)
        assert result.remaining_messages == 1
        assert llm.calls == 1

    def test_size_trigger_fires_below_message_threshold(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20, size=4000)
        big = messages(*range(1, 6), content="x" * 4000)
        result = run_compact(compactor, big, conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert result.compaction.first_message_id == 1

    def test_exactly_20_with_threshold_20(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20)
        result = run_compact(compactor, messages(*range(1, 21)), conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert result.compaction.last_message_id == 20
        assert result.remaining_messages == 0

    def test_19_messages_no_normal_compaction(self) -> None:
        store = FakeStore()
        compactor, llm = make_compactor(store, message=20)
        result = run_compact(compactor, messages(*range(1, 20)), conversation_id=1)
        assert not result.compacted
        assert llm.calls == 0

    def test_21_messages_compacts_only_one_bounded_window(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20, window=20)
        result = run_compact(compactor, messages(*range(1, 22)), conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert (
            result.compaction.first_message_id,
            result.compaction.last_message_id,
        ) == (1, 20)
        assert result.remaining_messages == 1
        assert len(store.saved) == 1


class TestForce:
    def test_force_compacts_below_threshold(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20)
        result = run_compact(
            compactor, messages(*range(1, 5)), conversation_id=1, force=True
        )
        assert result.compacted
        assert result.compaction is not None
        assert (
            result.compaction.first_message_id,
            result.compaction.last_message_id,
        ) == (1, 4)

    def test_force_with_no_uncompacted_messages_is_noop(self) -> None:
        store = FakeStore()
        compactor, llm = make_compactor(store, message=20)
        assert run_compact(
            compactor, messages(*range(1, 5)), conversation_id=1, force=True
        ).compacted
        result = run_compact(
            compactor, messages(*range(1, 5)), conversation_id=1, force=True
        )
        assert not result.compacted
        assert result.remaining_messages == 0
        assert llm.calls == 1

    def test_force_respects_max_window(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20, window=10)
        result = run_compact(
            compactor, messages(*range(1, 31)), conversation_id=1, force=True
        )
        assert result.compacted
        assert result.compaction is not None
        assert (
            result.compaction.first_message_id,
            result.compaction.last_message_id,
        ) == (1, 10)
        assert result.remaining_messages == 20

    def test_additional_work_detectable_after_bounded_force(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20, window=10)
        result = run_compact(
            compactor, messages(*range(1, 31)), conversation_id=1, force=True
        )
        assert result.compacted
        assert result.remaining_messages == 20


class TestIncremental:
    def test_first_compaction_starts_at_first_message(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20)
        result = run_compact(compactor, messages(*range(1, 41)), conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert (
            result.compaction.first_message_id,
            result.compaction.last_message_id,
        ) == (1, 20)

    def test_second_compaction_starts_after_previous_boundary(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20)
        msgs = messages(*range(1, 41))
        run_compact(compactor, msgs, conversation_id=1)
        second = run_compact(compactor, msgs, conversation_id=1)
        assert second.compacted
        assert second.compaction is not None
        assert (
            second.compaction.first_message_id,
            second.compaction.last_message_id,
        ) == (21, 40)
        assert second.remaining_messages == 0

    def test_noop_after_all_compacted(self) -> None:
        store = FakeStore()
        compactor, llm = make_compactor(store, message=20)
        msgs = messages(*range(1, 41))
        assert run_compact(compactor, msgs, conversation_id=1).compacted
        assert run_compact(compactor, msgs, conversation_id=1).compacted
        result = run_compact(compactor, msgs, conversation_id=1)
        assert not result.compacted
        assert result.remaining_messages == 0
        assert llm.calls == 2

    def test_already_compacted_messages_never_reprocessed(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20)
        msgs = messages(*range(1, 41))
        run_compact(compactor, msgs, conversation_id=1)
        run_compact(compactor, msgs, conversation_id=1)
        ranges = [
            (c.first_message_id, c.last_message_id)
            for c in store.list_for_conversation(1)
        ]
        assert ranges == [(1, 20), (21, 40)]
        assert ranges[0][1] < ranges[1][0]

    def test_fewer_remaining_than_max_window_all_selected(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20, window=20)
        msgs = messages(*range(1, 25))
        run_compact(compactor, msgs, conversation_id=1)
        second = run_compact(compactor, msgs, conversation_id=1, force=True)
        assert second.compacted
        assert second.compaction is not None
        assert (
            second.compaction.first_message_id,
            second.compaction.last_message_id,
        ) == (21, 24)
        assert second.remaining_messages == 0


class TestBoundary:
    def test_non_contiguous_boundary_preserved(self) -> None:
        store = FakeStore()
        store.save(
            make_compaction(
                compaction_id="c1",
                conversation_id=1,
                first_message_id=1,
                last_message_id=20,
            )
        )
        store.save(
            make_compaction(
                compaction_id="c2",
                conversation_id=1,
                first_message_id=50,
                last_message_id=70,
            )
        )
        compactor, llm = make_compactor(store, message=20, window=20)

        noop = run_compact(compactor, messages(*range(1, 71)), conversation_id=1)
        assert not noop.compacted
        assert noop.remaining_messages == 0
        assert llm.calls == 0

        result = run_compact(compactor, messages(*range(1, 101)), conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert (
            result.compaction.first_message_id,
            result.compaction.last_message_id,
        ) == (71, 90)

        ranges = [
            (c.first_message_id, c.last_message_id)
            for c in store.list_for_conversation(1)
        ]
        assert ranges == [(1, 20), (50, 70), (71, 90)]
        assert not any(21 <= first <= 49 or 21 <= last <= 49 for first, last in ranges)


class TestIdempotency:
    def test_repeated_invocation_is_idempotent_safe(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20)
        msgs = messages(*range(1, 21))
        first = run_compact(compactor, msgs, conversation_id=1)
        assert first.compacted
        second = run_compact(compactor, msgs, conversation_id=1)
        assert not second.compacted
        assert len(store.list_for_conversation(1)) == 1
        assert len(store.saved) == 1

    def test_duplicate_persistence_returns_existing_as_success(self) -> None:
        existing = make_compaction(
            compaction_id="dup-1",
            conversation_id=1,
            first_message_id=1,
            last_message_id=20,
        )
        store = FakeStore()
        store.preseed_hidden(existing)

        class DuplicateStub:
            async def extract(self, messages, *, conversation_id):
                return make_compaction(
                    compaction_id="dup-1",
                    conversation_id=1,
                    first_message_id=1,
                    last_message_id=20,
                )

        compactor = ConversationCompactor(
            store,
            DuplicateStub(),
            message_threshold=20,
            max_window=20,
            unit_threshold=None,
        )
        result = run_compact(compactor, messages(*range(1, 21)), conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert result.compaction.compaction_id == "dup-1"
        assert result.compaction == existing
        assert len(store.saved) == 0


class TestFailures:
    def test_extractor_failure_creates_no_compaction(self) -> None:
        store = FakeStore()
        extractor = RaisingExtractor(CompactionOutputError("malformed"))
        compactor = ConversationCompactor(
            store, extractor, message_threshold=20, max_window=20, unit_threshold=None
        )
        with pytest.raises(CompactionOutputError):
            run_compact(compactor, messages(*range(1, 21)), conversation_id=1)
        assert store.saved == []
        assert store.list_for_conversation(1) == []

    def test_provider_failure_creates_no_compaction(self) -> None:
        store = FakeStore()
        extractor = RaisingExtractor(CompactionProviderError("provider down"))
        compactor = ConversationCompactor(
            store, extractor, message_threshold=20, max_window=20, unit_threshold=None
        )
        with pytest.raises(CompactionProviderError):
            run_compact(compactor, messages(*range(1, 21)), conversation_id=1)
        assert store.saved == []

    def test_storage_failure_does_not_report_success(self) -> None:
        store = FakeStore()
        store.fail_save = CompactionCorruptError("disk full")
        compactor, _ = make_compactor(store, message=20)
        with pytest.raises(CompactionCorruptError):
            run_compact(compactor, messages(*range(1, 21)), conversation_id=1)
        assert store.saved == []

    def test_malformed_llm_output_does_not_advance_boundary(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20, llm_response="not json at all")
        msgs = messages(*range(1, 21))
        with pytest.raises(CompactionOutputError):
            run_compact(compactor, msgs, conversation_id=1)
        assert store.saved == []
        with pytest.raises(CompactionOutputError):
            run_compact(compactor, msgs, conversation_id=1)
        assert store.saved == []

    def test_failure_does_not_mutate_raw_messages(self) -> None:
        store = FakeStore()
        store.fail_save = CompactionCorruptError("disk full")
        compactor, _ = make_compactor(store, message=20)
        msgs = messages(*range(1, 21))
        with pytest.raises(CompactionCorruptError):
            run_compact(compactor, msgs, conversation_id=1)
        assert [m.id for m in msgs] == list(range(1, 21))


class TestPersistence:
    def test_successful_extraction_persists_exactly_one(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20)
        result = run_compact(compactor, messages(*range(1, 21)), conversation_id=1)
        assert result.compacted
        assert len(store.saved) == 1
        assert store.get(result.compaction.compaction_id) == result.compaction

    def test_compaction_version_passed_consistently(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20, compaction_version=2)
        result = run_compact(compactor, messages(*range(1, 21)), conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert result.compaction.compaction_version == 2
        assert store.saved[0].compaction_version == 2


class TestIsolation:
    def test_conversation_a_does_not_compact_conversation_b(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=2)
        msgs = messages(*range(1, 5))
        r_a = run_compact(compactor, msgs, conversation_id=1)
        r_b = run_compact(compactor, msgs, conversation_id=2)
        assert r_a.compacted and r_b.compacted
        a_compactions = store.list_for_conversation(1)
        b_compactions = store.list_for_conversation(2)
        assert all(c.conversation_id == 1 for c in a_compactions)
        assert all(c.conversation_id == 2 for c in b_compactions)
        assert a_compactions[0].compaction_id != b_compactions[0].compaction_id


class TestConfigurability:
    def test_configurable_message_threshold(self) -> None:
        store = FakeStore()
        compactor, llm = make_compactor(store, message=5)
        assert not run_compact(
            compactor, messages(*range(1, 5)), conversation_id=1
        ).compacted
        assert run_compact(
            compactor, messages(*range(1, 6)), conversation_id=1
        ).compacted
        assert llm.calls == 1

    def test_configurable_max_window(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20, window=8)
        result = run_compact(compactor, messages(*range(1, 21)), conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert (
            result.compaction.first_message_id,
            result.compaction.last_message_id,
        ) == (1, 8)
        assert result.remaining_messages == 12


class TestEdgeCases:
    def test_empty_conversation_deterministic_noop(self) -> None:
        store = FakeStore()
        compactor, llm = make_compactor(store, message=20)
        result = run_compact(compactor, (), conversation_id=1)
        assert not result.compacted
        assert result.compaction is None
        assert result.remaining_messages == 0
        assert llm.calls == 0

    def test_original_messages_not_mutated(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20)
        msgs = messages(*range(1, 21))
        original = tuple(msgs)
        run_compact(compactor, msgs, conversation_id=1)
        assert msgs == original
        assert [m.id for m in msgs] == list(range(1, 21))

    def test_trigger_calculation_does_not_call_llm(self) -> None:
        store = FakeStore()
        compactor, llm = make_compactor(store, message=20)
        run_compact(compactor, messages(*range(1, 5)), conversation_id=1)
        assert llm.calls == 0

    def test_trigger_calculation_does_not_write_storage(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=20)
        run_compact(compactor, messages(*range(1, 5)), conversation_id=1)
        assert store.saved == []
        assert store.list_for_conversation(1) == []

    def test_fewer_messages_than_max_window_all_selected(self) -> None:
        store = FakeStore()
        compactor, _ = make_compactor(store, message=3, window=10)
        result = run_compact(compactor, messages(*range(1, 5)), conversation_id=1)
        assert result.compacted
        assert result.compaction is not None
        assert (
            result.compaction.first_message_id,
            result.compaction.last_message_id,
        ) == (1, 4)


class TestIntegration:
    def test_real_store_pipeline_no_memory_db(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from friday import config

        monkeypatch.setattr(config.config, "FRIDAY_HOME", tmp_path)
        db_path = tmp_path / "data" / "conversations.db"

        with SQLiteConversationStore(db_path) as conv_store:
            conv = conv_store.create_conversation()
            for i in range(1, 6):
                conv_store.save_message(conv.id, "user", f"Message {i}")
            stored = conv_store.get_recent_messages(conv.id, limit=20)
        msgs = [Msg(m.id, m.role, m.content) for m in stored]

        with SQLiteCompactionStore(db_path) as cstore:
            llm = FakeLLM(EMPTY_JSON)
            extractor = ConversationCompactionExtractor(llm)
            compactor = ConversationCompactor(
                cstore,
                extractor,
                message_threshold=20,
                max_window=20,
                unit_threshold=None,
            )
            result = run_compact(compactor, msgs, conversation_id=conv.id, force=True)
            assert result.compacted
            assert result.compaction is not None
            assert result.compaction.conversation_id == conv.id
            assert cstore.get(result.compaction.compaction_id) == result.compaction

        assert db_path.exists()
        assert not (tmp_path / "data" / "memory.db").exists()

    def test_no_memory_resolver_interaction(self) -> None:
        import friday.compaction.compactor as module

        source = inspect.getsource(module)
        for forbidden in (
            "MemoryResolver",
            "MemoryCandidate",
            "durable_manager",
            "resolver",
            "candidates",
        ):
            assert forbidden not in source

    def test_no_context_manager_interaction(self) -> None:
        import friday.compaction.compactor as module

        source = inspect.getsource(module)
        for forbidden in ("ContextManager", "ContextShrinker", "context.manager"):
            assert forbidden not in source
