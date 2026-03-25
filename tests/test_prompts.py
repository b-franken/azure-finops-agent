"""Tests for the prompt loader."""

from src.prompts import load_prompt


class TestLoadPrompt:
    def test_loads_instructions_and_description(self) -> None:
        instructions, description = load_prompt("cost-analyzer")
        assert "cost analysis specialist" in instructions
        assert "Analyzes Azure spend" in description

    def test_all_agents_loadable(self) -> None:
        agents = [
            "cost-analyzer",
            "waste-detector",
            "advisor",
            "anomaly-detector",
            "budget-tracker",
            "tag-analyzer",
            "reporter",
            "triage",
        ]
        for name in agents:
            instructions, description = load_prompt(name)
            assert instructions, f"{name} has empty instructions"
            assert description, f"{name} has empty description"

    def test_triage_has_placeholders(self) -> None:
        instructions, _ = load_prompt("triage")
        assert "{cost_desc}" in instructions
        assert "{reporter_desc}" in instructions
