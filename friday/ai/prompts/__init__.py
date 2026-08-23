"""
Prompt loading helpers.
"""

from pathlib import Path

from . import templates


def load_system_prompt() -> str:
    """Load the core persona prompt."""
    return Path(__file__).with_name("persona.md").read_text(encoding="utf-8").strip()


def load_safety_prompt() -> str:
    """Load safety guidelines."""
    return Path(__file__).with_name("safety.md").read_text(encoding="utf-8").strip()


def load_tool_rules_prompt() -> str:
    """Load tool usage rules."""
    return Path(__file__).with_name("tool_rules.md").read_text(encoding="utf-8").strip()


def load_formatting_prompt() -> str:
    """Load formatting guidelines."""
    return Path(__file__).with_name("formatting.md").read_text(encoding="utf-8").strip()


def load_behavior_prompt() -> str:
    """Load behavior guidelines."""
    return Path(__file__).with_name("behavior.md").read_text(encoding="utf-8").strip()


def load_full_system_prompt() -> str:
    """Load the complete system prompt with all sections."""
    parts = [
        load_system_prompt(),
        "",
        "---",
        "",
        load_safety_prompt(),
        "",
        "---",
        "",
        load_tool_rules_prompt(),
        "",
        "---",
        "",
        load_formatting_prompt(),
        "",
        "---",
        "",
        load_behavior_prompt(),
    ]
    return "\n".join(parts)


def register_all_prompts(mcp):
    templates.register(mcp)
