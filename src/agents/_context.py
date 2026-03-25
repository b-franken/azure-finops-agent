"""Shared Azure client singleton for LangGraph tools."""

from __future__ import annotations

import threading

from src.azure_clients import AzureClients, create_azure_clients

_lock = threading.Lock()
_clients: AzureClients | None = None


def get_clients() -> AzureClients:
    global _clients
    if _clients is None:
        with _lock:
            if _clients is None:
                _clients = create_azure_clients()
    return _clients


def reset_clients() -> None:
    global _clients
    with _lock:
        _clients = None
