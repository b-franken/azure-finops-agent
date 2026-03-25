"""Tests for tag analyzer tools."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.agents.tag_analyzer import (
    find_resources_missing_tag,
    find_untagged_resources,
    tag_coverage_report,
)


def _mock_graph_response(rows: list[dict]) -> MagicMock:
    response = MagicMock()
    response.data = rows
    response.skip_token = None
    return response


class TestFindUntaggedResources:
    def test_finds_untagged(self, mock_azure_clients) -> None:
        mock_azure_clients.graph.resources.return_value = _mock_graph_response(
            [
                {
                    "name": "vm-noTags",
                    "type": "virtualMachines",
                    "resourceGroup": "rg-dev",
                    "location": "westeurope",
                },
            ]
        )
        result = find_untagged_resources.func()
        assert "vm-noTags" in result
        assert "1 resource" in result

    def test_no_untagged(self, mock_azure_clients) -> None:
        mock_azure_clients.graph.resources.return_value = _mock_graph_response([])
        result = find_untagged_resources.func()
        assert "All resources" in result or "0 resource" in result


class TestFindResourcesMissingTag:
    def test_finds_missing(self, mock_azure_clients) -> None:
        mock_azure_clients.graph.resources.return_value = _mock_graph_response(
            [
                {
                    "name": "vm-1",
                    "type": "virtualMachines",
                    "resourceGroup": "rg-1",
                },
            ]
        )
        result = find_resources_missing_tag.func("environment")
        assert "vm-1" in result

    def test_invalid_tag_key(self, mock_azure_clients) -> None:
        result = find_resources_missing_tag.func("'; DROP TABLE--")
        assert "invalid" in result.lower()


class TestTagCoverageReport:
    def test_returns_coverage_table(self, mock_azure_clients) -> None:
        mock_azure_clients.graph.resources.return_value = _mock_graph_response(
            [
                {"type": "virtualMachines", "total": 10, "tagged": 8},
                {"type": "storageAccounts", "total": 5, "tagged": 5},
            ]
        )
        result = tag_coverage_report.func()
        assert "Coverage" in result or "OVERALL" in result
