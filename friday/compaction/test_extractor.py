"""Tests for Phase 4 M3 compaction extraction (LLM -> validated ConversationCompaction)."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass

import pytest

from friday.compaction.exceptions import CompactionOutputError, CompactionProviderError
from friday.compaction.extractor import ConversationCompactionExtractor
from friday.compaction.models import ConversationCompaction


@dataclass(frozen=True, slots=True)
class Msg:
    id: int
    role: str = "user"
    content: str = ""


def window(*ids: int) -> tuple[Msg, ...]:
    return tuple(Msg(message_id) for message_id in ids)


VALID_JSON = """{
  "summary": "Designed the compaction subsystem.",
  "facts": [
    {"content": "Compaction is incremental.", "source_message_ids": [1, 2]}
  ],
  "decisions": [
    {"content": "Use SQLite for storage.", "source_message_ids": [3]}
  ],
  "changes": [],
  "open_questions": [
    {"content": "Is async needed?", "source_message_ids": [4]}
  ]
}"""


class FakeLLM:
    def __init__(self, response: str) -> None:
        self._response = response
        self.last_system: str | None = None
        self.last_user: str | None = None
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        self.last_system = system
        self.last_user = user
        return self._response


class RaisingLLM:
    async def complete(self, system: str, user: str) -> str:
        raise RuntimeError("provider down")


def extract(
    compaction_json: str,
    *,
    conversation_id: int = 1,
    llm: FakeLLM | RaisingLLM | None = None,
):
    fake = llm if llm is not None else FakeLLM(compaction_json)
    extractor = ConversationCompactionExtractor(fake)
    result = asyncio.run(
        extractor.extract(window(1, 2, 3, 4), conversation_id=conversation_id)
    )
    return result, fake


class TestExtraction:
    def test_valid_complete_json(self) -> None:
        result, _ = extract(VALID_JSON)
        assert isinstance(result, ConversationCompaction)
        assert result.summary == "Designed the compaction subsystem."
        assert len(result.facts) == 1
        assert result.facts[0].content == "Compaction is incremental."
        assert result.facts[0].source_message_ids == (1, 2)
        assert result.decisions[0].content == "Use SQLite for storage."
        assert result.open_questions[0].content == "Is async needed?"

    def test_valid_summary_with_empty_categories(self) -> None:
        json_text = """{"summary": "Brief conversation about testing.", "facts": [], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert result.summary == "Brief conversation about testing."
        assert result.facts == ()
        assert result.decisions == ()
        assert result.changes == ()
        assert result.open_questions == ()

    def test_missing_category_treated_as_empty(self) -> None:
        json_text = """{"summary": "Summary.", "facts": [], "decisions": []}"""
        result, _ = extract(json_text)
        assert result.changes == ()
        assert result.open_questions == ()

    def test_missing_summary_treated_as_empty(self) -> None:
        json_text = """{"facts": [{"content": "A fact.", "source_message_ids": [1]}], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert result.summary == ""

    def test_result_satisfies_m1_invariants(self) -> None:
        result, _ = extract(VALID_JSON)
        assert result.first_message_id == 1
        assert result.last_message_id == 4
        assert result.conversation_id == 1
        for category in (
            result.facts,
            result.decisions,
            result.changes,
            result.open_questions,
        ):
            for item in category:
                assert all(1 <= mid <= 4 for mid in item.source_message_ids)


class TestPromptSafety:
    def test_prompt_contains_quoted_data_boundary(self) -> None:
        _, fake = extract(VALID_JSON)
        assert fake.last_system is not None
        lowered = fake.last_system.lower()
        assert "quoted conversation content" in lowered
        assert "not instructions" in lowered
        assert "must not be followed" in lowered

    def test_fake_llm_receives_expected_transcript(self) -> None:
        _, fake = extract(VALID_JSON)
        assert fake.last_user is not None
        assert "[1] user: " in fake.last_user
        assert "[4] user: " in fake.last_user
        assert fake.last_user.index("[1]") < fake.last_user.index("[4]")


class TestParsing:
    def test_json_inside_markdown_fences(self) -> None:
        result, _ = extract(f"```json\n{VALID_JSON}\n```")
        assert result.summary == "Designed the compaction subsystem."

    def test_harmless_surrounding_text(self) -> None:
        result, _ = extract(f"Here is the result:\n\n{VALID_JSON}\n\nHope that helps!")
        assert result.summary == "Designed the compaction subsystem."

    def test_malformed_json_fails_safely(self) -> None:
        with pytest.raises(CompactionOutputError):
            extract("this is not json at all")

    def test_top_level_list_fails_safely(self) -> None:
        with pytest.raises(CompactionOutputError):
            extract('[{"content": "A fact.", "source_message_ids": [1]}]')

    def test_object_without_recognized_keys_fails_safely(self) -> None:
        with pytest.raises(CompactionOutputError):
            extract('{"unrelated": true}')

    def test_non_list_category_fails_safely(self) -> None:
        with pytest.raises(CompactionOutputError):
            extract(
                '{"summary": "S.", "facts": "not-a-list", "decisions": [], "changes": [], "open_questions": []}'
            )

    def test_non_string_summary_fails_safely(self) -> None:
        with pytest.raises(CompactionOutputError):
            extract(
                '{"summary": 42, "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            )

    def test_unknown_category_ignored(self) -> None:
        json_text = """{"summary": "S.", "gossip": [{"content": "X.", "source_message_ids": [1]}], "facts": [], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert result.facts == ()

    def test_non_object_item_skipped(self) -> None:
        json_text = """{"summary": "S.", "facts": [42, "x", {"content": "A fact.", "source_message_ids": [1]}], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert len(result.facts) == 1


class TestItemValidation:
    def test_item_with_empty_content_dropped(self) -> None:
        json_text = """{"summary": "S.", "facts": [{"content": "", "source_message_ids": [1]}], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert result.facts == ()

    def test_item_with_empty_source_message_ids_dropped(self) -> None:
        json_text = """{"summary": "S.", "facts": [{"content": "A fact.", "source_message_ids": []}], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert result.facts == ()

    def test_item_referencing_unknown_message_id_dropped(self) -> None:
        json_text = """{"summary": "S.", "facts": [{"content": "A fact.", "source_message_ids": [999]}], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert result.facts == ()

    def test_item_referencing_outside_window_dropped(self) -> None:
        json_text = """{"summary": "S.", "facts": [{"content": "A fact.", "source_message_ids": [5]}], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert result.facts == ()

    def test_partially_unknown_source_ids_filtered(self) -> None:
        json_text = """{"summary": "S.", "facts": [{"content": "A fact.", "source_message_ids": [1, 999]}], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert len(result.facts) == 1
        assert result.facts[0].source_message_ids == (1,)

    def test_duplicate_source_ids_deduplicated(self) -> None:
        json_text = """{"summary": "S.", "facts": [{"content": "A fact.", "source_message_ids": [1, 1, 2]}], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert result.facts[0].source_message_ids == (1, 2)

    def test_multiple_source_ids_accepted(self) -> None:
        json_text = """{"summary": "S.", "facts": [{"content": "A fact.", "source_message_ids": [1, 2, 3, 4]}], "decisions": [], "changes": [], "open_questions": []}"""
        result, _ = extract(json_text)
        assert result.facts[0].source_message_ids == (1, 2, 3, 4)


class TestRangeDerivation:
    def test_first_last_derived_from_input_not_llm(self) -> None:
        json_text = """{"summary": "S.", "first_message_id": 100, "last_message_id": 200, "facts": [], "decisions": [], "changes": [], "open_questions": []}"""
        extractor = ConversationCompactionExtractor(FakeLLM(json_text))
        result = asyncio.run(extractor.extract(window(7, 8, 9), conversation_id=3))
        assert result.first_message_id == 7
        assert result.last_message_id == 9
        assert result.conversation_id == 3

    def test_empty_input_window_rejected(self) -> None:
        extractor = ConversationCompactionExtractor(FakeLLM(VALID_JSON))
        with pytest.raises(ValueError):
            asyncio.run(extractor.extract((), conversation_id=1))


class TestFailures:
    def test_llm_raises_exception(self) -> None:
        extractor = ConversationCompactionExtractor(RaisingLLM())
        with pytest.raises(CompactionProviderError):
            asyncio.run(extractor.extract(window(1, 2, 3), conversation_id=1))

    def test_llm_returns_empty_output(self) -> None:
        with pytest.raises(CompactionOutputError):
            extract("")


class TestItemIdentity:
    def test_deterministic_item_ids(self) -> None:
        first, _ = extract(VALID_JSON)
        second, _ = extract(VALID_JSON)
        assert first.facts[0].item_id == second.facts[0].item_id
        assert first.decisions[0].item_id == second.decisions[0].item_id

    def test_same_input_same_compaction_id(self) -> None:
        first, _ = extract(VALID_JSON)
        second, _ = extract(VALID_JSON)
        assert first.compaction_id == second.compaction_id

    def test_different_content_produces_different_item_id(self) -> None:
        json_a = """{"summary": "S.", "facts": [{"content": "Fact A.", "source_message_ids": [1]}], "decisions": [], "changes": [], "open_questions": []}"""
        json_b = """{"summary": "S.", "facts": [{"content": "Fact B.", "source_message_ids": [1]}], "decisions": [], "changes": [], "open_questions": []}"""
        a, _ = extract(json_a)
        b, _ = extract(json_b)
        assert a.facts[0].item_id != b.facts[0].item_id

    def test_different_provenance_produces_different_item_id(self) -> None:
        json_a = """{"summary": "S.", "facts": [{"content": "Fact A.", "source_message_ids": [1]}], "decisions": [], "changes": [], "open_questions": []}"""
        json_b = """{"summary": "S.", "facts": [{"content": "Fact A.", "source_message_ids": [2]}], "decisions": [], "changes": [], "open_questions": []}"""
        a, _ = extract(json_a)
        b, _ = extract(json_b)
        assert a.facts[0].item_id != b.facts[0].item_id


class TestIsolation:
    def test_no_database_or_storage_interaction(self) -> None:
        import friday.compaction.extractor as module

        source = inspect.getsource(module)
        assert "sqlite" not in source.lower()

    def test_extractor_has_no_storage_handle(self) -> None:
        extractor = ConversationCompactionExtractor(FakeLLM(VALID_JSON))
        assert not hasattr(extractor, "_store")
        assert not hasattr(extractor, "_db")
