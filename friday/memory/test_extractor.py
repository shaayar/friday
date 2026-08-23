"""Tests for MemoryExtractor: bounded window, JSON parsing, relevance gate."""

from __future__ import annotations

import pytest

from friday.memory.extractor import MemoryExtractor
from friday.memory.models import (
    MemoryConfidence,
    MemoryScope,
    MemoryType,
)


class FakeLLM:
    """Fake LLM that records the last transcript and returns a fixed response."""

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


def message(message_id: str, role: str, content: str) -> tuple[str, str, str]:
    return (message_id, role, content)


def messages_from(*pairs: tuple[str, str, str]) -> list[tuple[str, str, str]]:
    return list(pairs)


VALID_JSON = """[
  {"content": "User prefers dark mode.", "type": "user_fact", "confidence": "explicit", "reasoning": "stated clearly"},
  {"content": "User is learning Rust.", "type": "user_fact", "confidence": "inferred"},
  {"content": "The project uses Next.js.", "type": "project_fact", "confidence": "explicit"}
]"""


class TestExtraction:
    def _extractor(self, llm: FakeLLM | RaisingLLM, **kwargs) -> MemoryExtractor:
        return MemoryExtractor(llm, **kwargs)

    @pytest.mark.asyncio
    async def test_valid_candidates_mapped(self) -> None:
        llm = FakeLLM(VALID_JSON)
        extractor = self._extractor(llm)
        candidates = await extractor.extract(
            messages_from(
                message("m1", "user", "I prefer dark mode."),
                message("m2", "assistant", "Got it."),
                message("m3", "user", "I am learning Rust."),
            ),
            conversation_id="conv-1",
        )

        assert len(candidates) == 2
        user_fact, rust_fact = candidates
        assert user_fact.type is MemoryType.USER_FACT
        assert user_fact.scope is MemoryScope.USER
        assert user_fact.confidence is MemoryConfidence.EXPLICIT
        assert user_fact.source_conversation_id == "conv-1"
        assert user_fact.source_message_ids == ("m1", "m3")
        assert user_fact.reasoning == "stated clearly"

        assert rust_fact.type is MemoryType.USER_FACT
        assert rust_fact.confidence is MemoryConfidence.INFERRED
        assert rust_fact.source_message_ids == ("m1", "m3")

    @pytest.mark.asyncio
    async def test_project_fact_with_project_id(self) -> None:
        llm = FakeLLM(VALID_JSON)
        extractor = self._extractor(llm)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "The project uses Next.js.")),
            conversation_id="conv-1",
            project_id="proj-1",
        )
        assert len(candidates) == 1
        assert candidates[0].type is MemoryType.PROJECT_FACT
        assert candidates[0].scope is MemoryScope.PROJECT
        assert candidates[0].project_id == "proj-1"

    @pytest.mark.asyncio
    async def test_project_fact_without_project_id_skipped(self) -> None:
        llm = FakeLLM(VALID_JSON)
        extractor = self._extractor(llm)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "The project uses Next.js.")),
            conversation_id="conv-1",
        )
        # Only the user facts survive; the project fact needs a project_id.
        assert [c.type for c in candidates] == [MemoryType.USER_FACT]
        assert all(c.project_id is None for c in candidates)

    @pytest.mark.asyncio
    async def test_window_respects_most_recent_only(self) -> None:
        llm = FakeLLM(VALID_JSON)
        extractor = self._extractor(llm, window_size=20)
        messages = [
            message(f"old-{i}", "user", f"Old statement {i}.") for i in range(30)
        ]
        await extractor.extract(messages, conversation_id="conv-1")

        assert llm.calls == 1
        assert llm.last_user is not None
        # Only the last 20 messages may appear in the transcript.
        assert "old-9" not in llm.last_user
        assert "old-10" in llm.last_user
        assert "old-29" in llm.last_user

    @pytest.mark.asyncio
    async def test_chronological_order_in_transcript(self) -> None:
        llm = FakeLLM(VALID_JSON)
        extractor = self._extractor(llm, window_size=20)
        await extractor.extract(
            messages_from(
                message("m1", "user", "First."),
                message("m2", "user", "Second."),
            ),
            conversation_id="conv-1",
        )
        assert llm.last_user is not None
        assert llm.last_user.index("First.") < llm.last_user.index("Second.")

    @pytest.mark.asyncio
    async def test_min_messages_not_met_skips_llm(self) -> None:
        llm = FakeLLM(VALID_JSON)
        extractor = self._extractor(llm, window_size=20, min_messages=2)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "Only one message.")),
            conversation_id="conv-1",
        )
        assert candidates == []
        assert llm.calls == 0

    @pytest.mark.asyncio
    async def test_empty_messages_returns_empty(self) -> None:
        llm = FakeLLM(VALID_JSON)
        extractor = self._extractor(llm)
        assert await extractor.extract([], conversation_id="conv-1") == []
        assert llm.calls == 0

    @pytest.mark.asyncio
    async def test_llm_failure_is_isolated(self) -> None:
        extractor = self._extractor(RaisingLLM())
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "Hello there.")),
            conversation_id="conv-1",
        )
        assert candidates == []


class TestParsing:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_empty(self) -> None:
        llm = FakeLLM("this is not json at all")
        extractor = MemoryExtractor(llm)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "Something.")),
            conversation_id="conv-1",
        )
        assert candidates == []

    @pytest.mark.asyncio
    async def test_markdown_fence_json_parsed(self) -> None:
        llm = FakeLLM(f"```json\n{VALID_JSON}\n```")
        extractor = MemoryExtractor(llm)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "Something.")),
            conversation_id="conv-1",
        )
        # In a single-message window the inferred + project facts are dropped.
        assert len(candidates) == 1
        assert candidates[0].content == "User prefers dark mode."

    @pytest.mark.asyncio
    async def test_top_level_object_with_facts_key(self) -> None:
        llm = FakeLLM(
            '{"facts": [{"content": "User likes tea.", "type": "user_fact"}]}'
        )
        extractor = MemoryExtractor(llm)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "I like tea.")),
            conversation_id="conv-1",
        )
        assert len(candidates) == 1
        assert candidates[0].content == "User likes tea."

    @pytest.mark.asyncio
    async def test_trivial_content_filtered(self) -> None:
        llm = FakeLLM(
            '[{"content": "okay", "type": "user_fact"},'
            '{"content": "Thanks!", "type": "user_fact"},'
            '{"content": "User likes tea.", "type": "user_fact"}]'
        )
        extractor = MemoryExtractor(llm)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "I like tea.")),
            conversation_id="conv-1",
        )
        assert len(candidates) == 1
        assert candidates[0].content == "User likes tea."

    @pytest.mark.asyncio
    async def test_invalid_type_skipped(self) -> None:
        llm = FakeLLM(
            '[{"content": "A fact.", "type": "gossip"},'
            '{"content": "User likes tea.", "type": "user_fact"}]'
        )
        extractor = MemoryExtractor(llm)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "I like tea.")),
            conversation_id="conv-1",
        )
        assert len(candidates) == 1
        assert candidates[0].content == "User likes tea."

    @pytest.mark.asyncio
    async def test_non_object_items_skipped(self) -> None:
        llm = FakeLLM(
            '[42, "string", {"content": "User likes tea.", "type": "user_fact"}]'
        )
        extractor = MemoryExtractor(llm)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "I like tea.")),
            conversation_id="conv-1",
        )
        assert len(candidates) == 1

    @pytest.mark.asyncio
    async def test_empty_content_skipped(self) -> None:
        llm = FakeLLM('[{"content": "", "type": "user_fact"}]')
        extractor = MemoryExtractor(llm)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "I like tea.")),
            conversation_id="conv-1",
        )
        assert candidates == []

    @pytest.mark.asyncio
    async def test_llm_supplied_message_ids_filtered_to_known(self) -> None:
        llm = FakeLLM(
            '[{"content": "User likes tea.", "type": "user_fact",'
            ' "message_ids": ["m1", "ghost-id"]}]'
        )
        extractor = MemoryExtractor(llm)
        candidates = await extractor.extract(
            messages_from(message("m1", "user", "I like tea.")),
            conversation_id="conv-1",
        )
        assert len(candidates) == 1
        assert candidates[0].source_message_ids == ("m1",)

    @pytest.mark.asyncio
    async def test_inferred_with_insufficient_messages_skipped(self) -> None:
        # Two messages but only one user message -> insufficient distinct ids.
        llm = FakeLLM(
            '[{"content": "User likes tea.", "type": "user_fact", "confidence": "inferred"}]'
        )
        extractor = MemoryExtractor(llm)
        candidates = await extractor.extract(
            messages_from(
                message("m1", "user", "I like tea."),
                message("m2", "assistant", "Nice."),
            ),
            conversation_id="conv-1",
        )
        assert candidates == []

    @pytest.mark.asyncio
    async def test_conversation_summary_scope(self) -> None:
        llm = FakeLLM(
            '[{"content": "The conversation covered dark mode preferences.",'
            ' "type": "conversation_summary"}]'
        )
        extractor = MemoryExtractor(llm)
        candidates = await extractor.extract(
            messages_from(
                message("m1", "user", "I prefer dark mode."),
                message("m2", "assistant", "Noted."),
            ),
            conversation_id="conv-1",
        )
        assert len(candidates) == 1
        summary = candidates[0]
        assert summary.type is MemoryType.CONVERSATION_SUMMARY
        assert summary.scope is MemoryScope.CONVERSATION
        assert summary.source_message_ids == ("m1", "m2")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
