"""Tests for ContextShrinker: LLM-backed history compression."""

from __future__ import annotations

import pytest

from friday.context.shrinker import ContextShrinker


class FakeLLM:
    def __init__(self, response: str) -> None:
        self._response = response
        self.last_system: str | None = None
        self.last_user: str | None = None

    def complete(self, system: str, user: str) -> str:
        self.last_system = system
        self.last_user = user
        return self._response


class RaisingLLM:
    def complete(self, system: str, user: str) -> str:
        raise RuntimeError("provider down")


def message(message_id: str, role: str, content: str) -> tuple[str, str, str]:
    return (message_id, role, content)


MESSAGES = [
    message("m1", "user", "I use Vim as my editor."),
    message("m2", "assistant", "Noted."),
    message("m3", "user", "I switched to Neovim last week."),
]


class TestContextShrinker:
    def test_shrink_returns_summary(self) -> None:
        llm = FakeLLM("User moved from Vim to Neovim.")
        shrinker = ContextShrinker(llm)
        result = shrinker.shrink(MESSAGES, max_units=100)
        assert result == "User moved from Vim to Neovim."

    def test_shrink_transcript_contains_messages(self) -> None:
        llm = FakeLLM("summary")
        shrinker = ContextShrinker(llm)
        shrinker.shrink(MESSAGES, max_units=100)
        assert llm.last_user is not None
        assert "I use Vim as my editor." in llm.last_user
        assert "switched to Neovim" in llm.last_user
        assert "m3" in llm.last_user

    def test_max_units_hint_in_prompt(self) -> None:
        llm = FakeLLM("summary")
        shrinker = ContextShrinker(llm)
        shrinker.shrink(MESSAGES, max_units=250)
        assert llm.last_system is not None
        assert "250" in llm.last_system

    def test_empty_messages_still_calls_llm(self) -> None:
        llm = FakeLLM("summary")
        shrinker = ContextShrinker(llm)
        result = shrinker.shrink([], max_units=100)
        assert result == "summary"

    def test_llm_failure_raises(self) -> None:
        shrinker = ContextShrinker(RaisingLLM())
        with pytest.raises(RuntimeError, match="provider"):
            shrinker.shrink(MESSAGES, max_units=100)

    def test_blank_response_raises(self) -> None:
        shrinker = ContextShrinker(FakeLLM("   "))
        with pytest.raises(RuntimeError, match="empty"):
            shrinker.shrink(MESSAGES, max_units=100)

    def test_result_is_stripped(self) -> None:
        llm = FakeLLM("\n  summary  \n")
        shrinker = ContextShrinker(llm)
        assert shrinker.shrink(MESSAGES, max_units=100) == "summary"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])