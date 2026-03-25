"""Prompt loader — reads agent instructions from markdown files."""

from __future__ import annotations

from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(agent_name: str) -> tuple[str, str]:
    """Load (instructions, description) from prompts/{agent_name}.md."""
    path = _PROMPTS_DIR / f"{agent_name}.md"
    text = path.read_text(encoding="utf-8")

    parts = text.split("---", 2)
    if len(parts) < 3:
        return text.strip(), ""

    metadata = yaml.safe_load(parts[1]) or {}
    instructions = parts[2].strip()
    return instructions, metadata.get("description", "")
