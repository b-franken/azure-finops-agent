"""Test fixtures — mock Azure clients for tool tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents._context import reset_clients


@pytest.fixture()
def mock_azure_clients():
    """Patch get_clients() singleton so tools use mock Azure clients."""
    clients = MagicMock()
    clients.subscription_ids = ["test-sub"]
    clients.cost_scopes = ["/subscriptions/test-sub"]

    reset_clients()
    with patch("src.agents._context.create_azure_clients", return_value=clients):
        yield clients
    reset_clients()
