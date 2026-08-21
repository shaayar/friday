"""M7.1b.3.1 Tests — Production Runtime Wiring.

Verifies that the dormant M7.1b.2 memory pipeline and M7.1b.3 compaction
pipeline are actually wired into the production FRIDAY runtime:

- the production ``LiveKitLLMBackend`` adapter (configured LLM -> LLMBackend);
- the ``AssistantSession`` sync dispatcher that schedules both post-turn
  pipelines as tracked, isolated background tasks;
- the ``agent_friday.py`` event hook that invokes the dispatcher.

These tests are deterministic and make no network calls: the LiveKit LLM is
faked, and the production adapter path (``build_llm_backend``) is exercised
with ``build_llm`` monkeypatched to return the fake.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from friday.ai.providers import LiveKitLLMBackend, build_llm_backend
from friday.compaction.compactor import ConversationCompactor
from friday.compaction.extractor import ConversationCompactionExtractor
from friday.core.session import AssistantSession, create_assistant_session
from friday.memory.extractor import MemoryExtractor

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

EXTRACTION_JSON = """[
  {"content": "User prefers dark mode.", "type": "user_fact", "confidence": "explicit", "message_ids": ["1"]}
]"""

COMPACTION_JSON = """{
  "summary": "Designed runtime wiring.",
  "facts": [{"content": "Memory pipeline is live.", "source_message_ids": [1]}],
  "decisions": [],
  "changes": [],
  "open_questions": []
}"""


class FakeLLMStream:
    """Duck-typed ``LLMStream``: ``collect()`` returns a ``CollectedResponse``-like."""

    def __init__(self, response: str) -> None:
        self._response = response

    async def collect(self) -> SimpleNamespace:
        return SimpleNamespace(text=self._response)


class FakeLiveKitLLM:
    """Duck-typed LiveKit LLM: sync ``chat()`` returning an async stream.

    Routes by system prompt so one fake can serve both pipelines.
    """

    def __init__(
        self,
        extraction_response: str = EXTRACTION_JSON,
        compaction_response: str = COMPACTION_JSON,
    ) -> None:
        self._extraction_response = extraction_response
        self._compaction_response = compaction_response
        self.chat_contexts: list = []
        self.calls = 0

    def chat(self, *, chat_ctx, **kwargs):
        self.calls += 1
        self.chat_contexts.append(chat_ctx)
        system_text = self._system_text(chat_ctx)
        if "extract durable, factual statements" in system_text:
            return FakeLLMStream(self._extraction_response)
        return FakeLLMStream(self._compaction_response)

    @staticmethod
    def _system_text(chat_ctx) -> str:
        return "\n".join(
            item.text_content or ""
            for item in chat_ctx.items
            if getattr(item, "role", None) == "system"
        )


class RaisingExtractionLLM(FakeLiveKitLLM):
    """Memory extraction path raises; compaction path succeeds."""

    def chat(self, *, chat_ctx, **kwargs):
        self.calls += 1
        self.chat_contexts.append(chat_ctx)
        if "extract durable, factual statements" in self._system_text(chat_ctx):
            raise RuntimeError("memory provider down")
        return FakeLLMStream(self._compaction_response)


class RaisingCompactionLLM(FakeLiveKitLLM):
    """Compaction path raises; memory extraction succeeds."""

    def chat(self, *, chat_ctx, **kwargs):
        self.calls += 1
        self.chat_contexts.append(chat_ctx)
        if "persistent compaction" in self._system_text(chat_ctx):
            raise RuntimeError("compaction provider down")
        return FakeLLMStream(self._extraction_response)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_friday_home(tmp_path, monkeypatch):
    """Temporary FRIDAY_HOME; isolates all three stores for the session."""
    from friday.config import config

    home = tmp_path / ".friday"
    monkeypatch.setattr(config, "FRIDAY_HOME", home)
    return home


async def flush_background(session: AssistantSession) -> None:
    """Run all tracked background tasks to completion."""
    while session._background_tasks:
        tasks = list(session._background_tasks)
        await asyncio.gather(*tasks, return_exceptions=True)


def make_backend(llm: FakeLiveKitLLM) -> LiveKitLLMBackend:
    return LiveKitLLMBackend(llm)


# =====================================================================
# 1. Production LLM backend adapter
# =====================================================================


class TestProductionBackend:
    @pytest.mark.asyncio
    async def test_production_llm_backend_implements_protocol(self) -> None:
        fake = FakeLiveKitLLM(compaction_response="COMPACTED OUTPUT")
        backend = make_backend(fake)

        assert asyncio.iscoroutinefunction(backend.complete)
        result = await backend.complete("system instructions", "user transcript")
        assert result == "COMPACTED OUTPUT"
        assert fake.calls == 1

        ctx = fake.chat_contexts[0]
        roles = [getattr(item, "role", None) for item in ctx.items]
        assert roles == ["system", "user"]

    def test_production_llm_backend_built_from_configured_provider(self, monkeypatch) -> None:
        from friday.ai import providers

        fake = FakeLiveKitLLM()
        monkeypatch.setattr(providers, "build_llm", lambda: fake)
        backend = build_llm_backend()
        assert isinstance(backend, LiveKitLLMBackend)
        assert backend._llm is fake

    @pytest.mark.asyncio
    async def test_production_backend_returns_expected_text(self) -> None:
        fake = FakeLiveKitLLM(compaction_response="EXPECTED TEXT")
        backend = make_backend(fake)
        assert await backend.complete("sys", "usr") == "EXPECTED TEXT"

    @pytest.mark.asyncio
    async def test_existing_memory_pipeline_runs_with_production_adapter(self) -> None:
        backend = make_backend(FakeLiveKitLLM())
        extractor = MemoryExtractor(llm=backend, window_size=20, min_messages=1)
        candidates = await extractor.extract(
            [("1", "user", "I prefer dark mode.")],
            conversation_id="conv-1",
        )
        assert len(candidates) == 1
        assert candidates[0].content == "User prefers dark mode."

    @pytest.mark.asyncio
    async def test_existing_compaction_pipeline_runs_with_production_adapter(self) -> None:
        @dataclass(frozen=True, slots=True)
        class Msg:
            id: int
            role: str = "user"
            content: str = "content"

        backend = make_backend(FakeLiveKitLLM())
        extractor = ConversationCompactionExtractor(llm=backend)
        compaction = await extractor.extract([Msg(1), Msg(2)], conversation_id=1)
        assert compaction.summary == "Designed runtime wiring."
        assert compaction.facts[0].content == "Memory pipeline is live."


# =====================================================================
# 2. AssistantSession production wiring
# =====================================================================


class TestSessionProductionWiring:
    @pytest.mark.asyncio
    async def test_assistant_session_receives_production_backend(
        self, temp_friday_home, monkeypatch
    ) -> None:
        from friday.ai import providers

        monkeypatch.setattr(providers, "build_llm", lambda: FakeLiveKitLLM())
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=build_llm_backend(),
        )
        assert session._memory_extractor is not None
        assert session._compactor is not None
        await session.stop()

    @pytest.mark.asyncio
    async def test_memory_extractor_is_constructed_in_production_path(
        self, temp_friday_home
    ) -> None:
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=make_backend(FakeLiveKitLLM()),
        )
        assert isinstance(session._memory_extractor, MemoryExtractor)
        await session.stop()

    @pytest.mark.asyncio
    async def test_compactor_is_constructed_in_production_path(
        self, temp_friday_home
    ) -> None:
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=make_backend(FakeLiveKitLLM()),
        )
        assert isinstance(session._compactor, ConversationCompactor)
        assert session._compaction_extractor is not None
        assert session._compaction_store is not None
        await session.stop()

    @pytest.mark.asyncio
    async def test_no_pipelines_without_backend(self, temp_friday_home) -> None:
        session = AssistantSession(friday_home=temp_friday_home)
        assert session._memory_extractor is None
        assert session._compactor is None
        assert session._compaction_store is None
        await session.stop()


# =====================================================================
# 3. Background dispatcher
# =====================================================================


class TestBackgroundDispatcher:
    async def _active_session(self, temp_friday_home) -> tuple[AssistantSession, FakeLiveKitLLM]:
        fake = FakeLiveKitLLM()
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=make_backend(fake),
        )
        session._extraction_interval = 1
        session._compactor._message_threshold = 1
        await session.start()
        session.conversation_store.save_message(session.conversation_id, "user", "I prefer dark mode.")
        return session, fake

    @pytest.mark.asyncio
    async def test_assistant_persistence_schedules_memory_task(self, temp_friday_home) -> None:
        session, fake = await self._active_session(temp_friday_home)
        try:
            session.on_assistant_persisted()
            assert len(session._background_tasks) == 2
            await flush_background(session)
            extraction_calls = [
                ctx
                for ctx in fake.chat_contexts
                if "extract durable, factual statements" in FakeLiveKitLLM._system_text(ctx)
            ]
            assert extraction_calls
        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_assistant_persistence_schedules_compaction_task(self, temp_friday_home) -> None:
        session, fake = await self._active_session(temp_friday_home)
        try:
            session.on_assistant_persisted()
            assert len(session._background_tasks) == 2
            await flush_background(session)
            compaction_calls = [
                ctx
                for ctx in fake.chat_contexts
                if "persistent compaction" in FakeLiveKitLLM._system_text(ctx)
            ]
            assert compaction_calls
        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_memory_and_compaction_use_tracked_background_tasks(
        self, temp_friday_home
    ) -> None:
        session, _ = await self._active_session(temp_friday_home)
        try:
            session.on_assistant_persisted()
            tasks = set(session._background_tasks)
            assert len(tasks) == 2
            assert all(isinstance(task, asyncio.Task) for task in tasks)
            await flush_background(session)
            assert len(session._background_tasks) == 0
        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_compaction_hook_is_actually_invoked(self, temp_friday_home) -> None:
        session, _ = await self._active_session(temp_friday_home)
        try:
            session.on_assistant_persisted()
            await flush_background(session)
            compactions = session._compaction_store.list_for_conversation(session.conversation_id)
            assert len(compactions) == 1
            assert compactions[0].summary == "Designed runtime wiring."
        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_memory_failure_does_not_stop_compaction(self, temp_friday_home) -> None:
        fake = RaisingExtractionLLM()
        session = AssistantSession(friday_home=temp_friday_home, llm_backend=make_backend(fake))
        session._extraction_interval = 1
        session._compactor._message_threshold = 1
        await session.start()
        session.conversation_store.save_message(session.conversation_id, "user", "I prefer dark mode.")
        try:
            session.on_assistant_persisted()
            await flush_background(session)
            compactions = session._compaction_store.list_for_conversation(session.conversation_id)
            assert len(compactions) == 1
        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_compaction_failure_does_not_stop_memory(self, temp_friday_home) -> None:
        fake = RaisingCompactionLLM()
        session = AssistantSession(friday_home=temp_friday_home, llm_backend=make_backend(fake))
        session._extraction_interval = 1
        await session.start()
        session.conversation_store.save_message(session.conversation_id, "user", "I prefer dark mode.")
        try:
            session.on_assistant_persisted()
            await flush_background(session)
            memories = session._memory_manager.get_active(valid_at=None, limit=100)
            assert any(m.content == "User prefers dark mode." for m in memories)
        finally:
            await session.stop()


# =====================================================================
# 4. Lifecycle correctness
# =====================================================================


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_rejected_background_coroutine_is_closed(self, temp_friday_home) -> None:
        session = AssistantSession(friday_home=temp_friday_home)
        session._stopping = True
        coro = session.on_assistant_message_persisted()
        task = session._schedule_background(coro)
        assert task is None
        with pytest.raises(RuntimeError):
            await coro
        await session.stop()

    def test_real_message_id_or_removed_dead_parameter(self) -> None:
        import agent_friday

        sig = inspect.signature(AssistantSession.on_assistant_message_persisted)
        assert "message_id" not in sig.parameters
        source = inspect.getsource(agent_friday)
        assert "on_assistant_persisted()" in source
        assert "message_id=0" not in source

    @pytest.mark.asyncio
    async def test_compaction_store_closes_on_stop(self, temp_friday_home) -> None:
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=make_backend(FakeLiveKitLLM()),
        )
        assert session._compaction_store is not None
        close_spy = MagicMock(wraps=session._compaction_store.close)
        session._compaction_store.close = close_spy
        await session.stop()
        close_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_waits_before_store_cleanup(self, temp_friday_home) -> None:
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=make_backend(FakeLiveKitLLM()),
        )
        order: list[str] = []
        orig_wait = session._wait_background_tasks

        async def wrapped_wait(timeout: float = 5.0) -> None:
            order.append("wait")
            await orig_wait(timeout)

        session._wait_background_tasks = wrapped_wait
        session._conversation_store.close = MagicMock(side_effect=lambda: order.append("close"))
        session._memory_store.close = MagicMock(side_effect=lambda: order.append("close"))
        if session._compaction_store is not None:
            session._compaction_store.close = MagicMock(side_effect=lambda: order.append("close"))

        await session.stop()
        assert "wait" in order
        assert order.index("wait") < order.index("close")


# =====================================================================
# 5. Production-path integration
# =====================================================================


class TestProductionPathIntegration:
    @pytest.mark.asyncio
    async def test_configured_llm_to_session_to_records(self, temp_friday_home) -> None:
        """Configured LLM -> production adapter -> AssistantSession -> records."""
        fake = FakeLiveKitLLM()
        session = await create_assistant_session(
            friday_home=temp_friday_home,
            llm_backend=make_backend(fake),
        )
        session._extraction_interval = 1
        session._compactor._message_threshold = 1
        conv_id = session.conversation_id
        try:
            for i in range(1, 4):
                session.conversation_store.save_message(conv_id, "user", f"Note {i}: I prefer dark mode.")

            session.on_assistant_persisted()
            await flush_background(session)

            memories = session._memory_manager.get_active(valid_at=None, limit=100)
            assert any(m.content == "User prefers dark mode." for m in memories)

            compactions = session._compaction_store.list_for_conversation(conv_id)
            assert len(compactions) == 1
            assert compactions[0].summary == "Designed runtime wiring."
        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_no_promotion_is_triggered(self, temp_friday_home) -> None:
        import agent_friday

        session = await create_assistant_session(
            friday_home=temp_friday_home,
            llm_backend=make_backend(FakeLiveKitLLM()),
        )
        try:
            session._extraction_interval = 1
            session.conversation_store.save_message(session.conversation_id, "user", "hello")
            session.on_assistant_persisted()
            await flush_background(session)
        finally:
            await session.stop()

        assert not hasattr(AssistantSession, "promote")
        handler_source = inspect.getsource(agent_friday.entrypoint)
        assert "on_assistant_persisted" in handler_source
        assert "promote" not in handler_source.lower()