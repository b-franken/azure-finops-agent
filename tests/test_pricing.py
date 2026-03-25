"""Tests for Azure Retail Prices API module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.pricing import (
    _validate_input,
    compare_sku_costs,
    get_monthly_cost,
    get_sku_price,
)

_HOURS_PER_MONTH = 730


class TestValidateInput:
    def test_accepts_valid_sku(self) -> None:
        _validate_input("Standard_D2s_v5", "sku_name")

    def test_accepts_region(self) -> None:
        _validate_input("westeurope", "region")

    def test_rejects_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            _validate_input("'; DROP TABLE--", "sku_name")

    def test_rejects_special_chars(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            _validate_input("sku&name=bad", "sku_name")


class TestGetSkuPrice:
    @patch("src.pricing.httpx.Client")
    def test_returns_price(self, mock_client_cls: MagicMock) -> None:
        get_sku_price.cache_clear()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "Items": [{"retailPrice": 0.192}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_client_cls.return_value.__enter__.return_value.get.return_value = (
            mock_response
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = get_sku_price("Standard_D2s_v5", "westeurope")
        assert result == 0.192

    @patch("src.pricing.httpx.Client")
    def test_returns_none_when_not_found(self, mock_client_cls: MagicMock) -> None:
        get_sku_price.cache_clear()
        mock_response = MagicMock()
        mock_response.json.return_value = {"Items": []}
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_client_cls.return_value.__enter__.return_value.get.return_value = (
            mock_response
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = get_sku_price("Nonexistent_SKU", "westeurope")
        assert result is None


class TestGetMonthlyCost:
    @patch("src.pricing.get_sku_price", return_value=0.10)
    def test_calculates_monthly(self, mock_price: MagicMock) -> None:
        result = get_monthly_cost("Standard_B2s", "westeurope")
        assert result == round(0.10 * _HOURS_PER_MONTH, 2)

    @patch("src.pricing.get_sku_price", return_value=None)
    def test_returns_none_when_no_price(self, mock_price: MagicMock) -> None:
        result = get_monthly_cost("Unknown", "westeurope")
        assert result is None


class TestCompareSkuCosts:
    @patch("src.pricing.get_monthly_cost")
    def test_calculates_savings(self, mock_cost: MagicMock) -> None:
        mock_cost.side_effect = [200.0, 50.0]
        result = compare_sku_costs("Standard_D8s_v5", "Standard_D2s_v5", "westeurope")
        assert result["monthly_savings"] == 150.0
        assert result["current_sku"] == "Standard_D8s_v5"
        assert result["target_sku"] == "Standard_D2s_v5"

    @patch("src.pricing.get_monthly_cost")
    def test_handles_missing_price(self, mock_cost: MagicMock) -> None:
        mock_cost.side_effect = [200.0, None]
        result = compare_sku_costs("Standard_D8s_v5", "Unknown", "westeurope")
        assert result["monthly_savings"] is None
