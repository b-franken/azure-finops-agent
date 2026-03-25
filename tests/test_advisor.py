"""Tests for advisor agent tools."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.agents.advisor import (
    get_prioritized_recommendations,
    get_reservation_recommendations,
)


def _make_recommendation(
    impact: str, short: str, action: str, resource_id: str
) -> MagicMock:
    rec = MagicMock()
    rec.impact = impact
    rec.short_description = MagicMock()
    rec.short_description.problem = short
    rec.short_description.solution = action
    rec.resource_metadata = MagicMock()
    rec.resource_metadata.resource_id = resource_id
    return rec


class TestGetPrioritizedRecommendations:
    def test_sorts_by_impact(self, mock_azure_clients) -> None:
        recs = [
            _make_recommendation("Low", "Minor fix", "Do X", "/sub/low"),
            _make_recommendation("High", "Right-size VM", "Downsize", "/sub/high"),
        ]
        advisor_mock = mock_azure_clients.advisor_for.return_value
        advisor_mock.recommendations.list.return_value = recs
        result = get_prioritized_recommendations.func()
        assert "HIGH" in result.upper() or "High" in result

    def test_empty(self, mock_azure_clients) -> None:
        advisor_mock = mock_azure_clients.advisor_for.return_value
        advisor_mock.recommendations.list.return_value = []
        result = get_prioritized_recommendations.func()
        assert "No cost optimization" in result


class TestGetReservationRecommendations:
    def test_filters_reservation_recs(self, mock_azure_clients) -> None:
        recs = [
            _make_recommendation(
                "Medium", "Buy reserved instance", "Purchase RI", "/sub/ri"
            ),
            _make_recommendation("High", "Right-size VM", "Downsize", "/sub/vm"),
        ]
        advisor_mock = mock_azure_clients.advisor_for.return_value
        advisor_mock.recommendations.list.return_value = recs
        result = get_reservation_recommendations.func()
        assert "reserved" in result.lower()
