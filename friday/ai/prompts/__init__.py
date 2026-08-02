"""
Prompt loading helpers.
"""

from pathlib import Path

from . import templates


def load_system_prompt() -> str:
    return Path(__file__).with_name("persona.md").read_text(encoding="utf-8").strip()


def register_all_prompts(mcp):
    templates.register(mcp)
