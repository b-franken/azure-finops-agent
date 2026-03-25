"""Tests for Azure management client creation and validation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.azure_clients import AzureClients, create_azure_clients, get_credential


class TestGetCredential:
    def test_uses_managed_identity_when_client_id_set(self) -> None:
        with patch.dict(os.environ, {"AZURE_CLIENT_ID": "test-id"}):
            cred = get_credential()
            assert type(cred).__name__ == "ManagedIdentityCredential"

    def test_uses_cli_credential_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            cred = get_credential()
            assert type(cred).__name__ == "AzureCliCredential"


class TestCreateAzureClients:
    @patch("src.azure_clients.MonitorManagementClient")
    @patch("src.azure_clients.ResourceGraphClient")
    @patch("src.azure_clients.CostManagementClient")
    @patch("src.azure_clients.get_credential")
    def test_parses_comma_separated_ids(
        self, mock_cred, mock_cost, mock_graph, mock_monitor
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "AZURE_SUBSCRIPTION_IDS": (
                    "aaaaaaaa-1111-2222-3333-444444444444,"
                    "bbbbbbbb-1111-2222-3333-444444444444"
                ),
            },
        ):
            clients = create_azure_clients()
            assert len(clients.subscription_ids) == 2

    @patch("src.azure_clients.MonitorManagementClient")
    @patch("src.azure_clients.ResourceGraphClient")
    @patch("src.azure_clients.CostManagementClient")
    @patch("src.azure_clients.get_credential")
    def test_single_subscription_fallback(
        self, mock_cred, mock_cost, mock_graph, mock_monitor
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "AZURE_SUBSCRIPTION_IDS": "",
                "AZURE_SUBSCRIPTION_ID": "aaaaaaaa-1111-2222-3333-444444444444",
            },
        ):
            clients = create_azure_clients()
            assert clients.subscription_ids == ["aaaaaaaa-1111-2222-3333-444444444444"]

    def test_missing_subscription_raises(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"AZURE_SUBSCRIPTION_IDS": "", "AZURE_SUBSCRIPTION_ID": ""},
                clear=False,
            ),
            pytest.raises(ValueError, match="Set AZURE_SUBSCRIPTION_IDS"),
        ):
            create_azure_clients()

    def test_invalid_uuid_raises(self) -> None:
        with (
            patch.dict(os.environ, {"AZURE_SUBSCRIPTION_IDS": "not-a-uuid"}),
            pytest.raises(ValueError, match="Invalid subscription ID"),
        ):
            create_azure_clients()


class TestAzureClientsProperties:
    def test_cost_scope_single_subscription(self) -> None:
        from unittest.mock import MagicMock

        clients = AzureClients(
            cost=MagicMock(),
            graph=MagicMock(),
            monitor=MagicMock(),
            subscription_ids=["sub-1"],
            _credential=MagicMock(),
        )
        assert clients.cost_scope == "/subscriptions/sub-1"

    def test_cost_scope_management_group(self) -> None:
        from unittest.mock import MagicMock

        clients = AzureClients(
            cost=MagicMock(),
            graph=MagicMock(),
            monitor=MagicMock(),
            subscription_ids=["sub-1"],
            _credential=MagicMock(),
            management_group_id="mg-1",
        )
        assert "/managementGroups/mg-1" in clients.cost_scope

    def test_cost_scopes_multi_subscription(self) -> None:
        from unittest.mock import MagicMock

        clients = AzureClients(
            cost=MagicMock(),
            graph=MagicMock(),
            monitor=MagicMock(),
            subscription_ids=["sub-1", "sub-2"],
            _credential=MagicMock(),
        )
        assert len(clients.cost_scopes) == 2
        assert clients.cost_scopes[0] == "/subscriptions/sub-1"
