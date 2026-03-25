"""Tests for waste detector tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.agents.waste_detector import (
    find_expensive_resources,
    find_idle_resources,
    find_orphaned_resources,
    find_oversized_resources,
    find_stale_resources,
    find_underutilized_vms,
)


def _mock_graph_response(columns: list[str], rows: list[list]) -> MagicMock:
    response = MagicMock()
    response.data = [dict(zip(columns, row, strict=False)) for row in rows]
    response.skip_token = None
    return response


def _empty_response() -> MagicMock:
    return _mock_graph_response([], [])


def _empties(n: int) -> list[MagicMock]:
    return [_empty_response() for _ in range(n)]


class TestFindIdleResources:
    def test_finds_stopped_vms(self, mock_azure_clients) -> None:
        vm_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "vmSize", "id"],
            [["vm-stopped", "rg-dev", "westeurope", "Standard_D2s_v5", "/sub/vm"]],
        )
        # idle: VMs, plans, LBs, AppGw, AvSets, DDoS, VNetGw, VNetGwConns
        mock_azure_clients.graph.resources.side_effect = [
            vm_resp,
            *_empties(7),
        ]
        result = find_idle_resources.func()
        assert "vm-stopped" in result

    def test_finds_empty_availability_sets(self, mock_azure_clients) -> None:
        avset_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "id"],
            [["avset-old", "rg-dev", "westeurope", "/sub/avset"]],
        )
        mock_azure_clients.graph.resources.side_effect = [
            *_empties(4),  # VMs, plans, LBs, AppGw
            avset_resp,  # AvSets
            *_empties(3),  # DDoS, VNetGw, VNetGwConns
        ]
        result = find_idle_resources.func()
        assert "avset-old" in result

    def test_finds_orphaned_vnet_gateways(self, mock_azure_clients) -> None:
        gw_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "gatewayType", "sku", "id"],
            [["gw-idle", "rg-dev", "westeurope", "Vpn", "VpnGw1", "/sub/gw"]],
        )
        mock_azure_clients.graph.resources.side_effect = [
            *_empties(6),  # VMs, plans, LBs, AppGw, AvSets, DDoS
            gw_resp,  # VNetGw
            _empty_response(),  # VNetGwConns (none → gw is orphaned)
        ]
        result = find_idle_resources.func()
        assert "gw-idle" in result


class TestFindOrphanedResources:
    def test_finds_orphaned_disks(self, mock_azure_clients) -> None:
        disk_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "sku", "diskSizeGb", "id"],
            [["disk-old", "rg-dev", "westeurope", "Premium_LRS", "128", "/sub/disk"]],
        )
        # orphaned: disks, NICs, IPs, NATs, snaps, NSGs, RTs, PEs, DNS, FDWAF, TM
        mock_azure_clients.graph.resources.side_effect = [
            disk_resp,
            *_empties(10),
        ]
        result = find_orphaned_resources.func()
        assert "disk-old" in result

    def test_finds_orphaned_nsgs(self, mock_azure_clients) -> None:
        nsg_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "id"],
            [["nsg-orphan", "rg-dev", "westeurope", "/sub/nsg"]],
        )
        mock_azure_clients.graph.resources.side_effect = [
            *_empties(5),  # disks, NICs, IPs, NATs, snaps
            nsg_resp,  # NSGs
            *_empties(5),  # RTs, PEs, DNS, FDWAF, TM
        ]
        result = find_orphaned_resources.func()
        assert "nsg-orphan" in result

    def test_finds_disconnected_private_endpoints(self, mock_azure_clients) -> None:
        pe_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "id"],
            [["pe-disconnected", "rg-dev", "westeurope", "/sub/pe"]],
        )
        mock_azure_clients.graph.resources.side_effect = [
            *_empties(7),  # disks, NICs, IPs, NATs, snaps, NSGs, RTs
            pe_resp,  # PEs
            *_empties(3),  # DNS, FDWAF, TM
        ]
        result = find_orphaned_resources.func()
        assert "pe-disconnected" in result


class TestFindOversizedResources:
    def test_finds_premium_databases(self, mock_azure_clients) -> None:
        db_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "tier", "capacity", "id"],
            [["db-dev", "rg-dev", "westeurope", "Premium", "125", "/sub/db"]],
        )
        # oversized: DBs, Plans, ElasticPools
        mock_azure_clients.graph.resources.side_effect = [
            db_resp,
            *_empties(2),
        ]
        result = find_oversized_resources.func()
        assert "db-dev" in result or "Premium" in result

    def test_finds_elastic_pools(self, mock_azure_clients) -> None:
        pool_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "sku", "tier", "id"],
            [["pool-1", "rg-dev", "westeurope", "StdPool", "Std", "/sub/pool"]],
        )
        mock_azure_clients.graph.resources.side_effect = [
            *_empties(2),  # DBs, Plans
            pool_resp,  # ElasticPools
        ]
        result = find_oversized_resources.func()
        assert "pool-1" in result


class TestFindStaleResources:
    def test_finds_storage_accounts(self, mock_azure_clients) -> None:
        storage_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "sku", "kind", "created", "id"],
            [
                [
                    "stold",
                    "rg-dev",
                    "westeurope",
                    "Standard_LRS",
                    "StorageV2",
                    "2025-01-01",
                    "/sub/st",
                ]
            ],
        )
        # stale: storage, KV, certs
        mock_azure_clients.graph.resources.side_effect = [
            storage_resp,
            *_empties(2),
        ]
        result = find_stale_resources.func()
        assert "stold" in result

    def test_finds_expired_certificates(self, mock_azure_clients) -> None:
        cert_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "expiresOn", "id"],
            [["cert-old", "rg-dev", "westeurope", "2024-01-01", "/sub/cert"]],
        )
        mock_azure_clients.graph.resources.side_effect = [
            *_empties(2),  # storage, KV
            cert_resp,  # certs
        ]
        result = find_stale_resources.func()
        assert "cert-old" in result


class TestFindUnderutilizedVms:
    @patch("src.metrics.get_avg_cpu", return_value=3.5)
    def test_finds_underutilized(self, mock_cpu, mock_azure_clients) -> None:
        vm_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "vmSize", "id"],
            [["vm-idle", "rg-dev", "westeurope", "Standard_D2s_v5", "/sub/vm"]],
        )
        mock_azure_clients.graph.resources.return_value = vm_resp
        mock_azure_clients.monitor = MagicMock()
        result = find_underutilized_vms.func(10.0)
        assert "vm-idle" in result
        assert "3.5%" in result

    @patch("src.metrics.get_avg_cpu", return_value=50.0)
    def test_no_underutilized(self, mock_cpu, mock_azure_clients) -> None:
        vm_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "vmSize", "id"],
            [["vm-busy", "rg-dev", "westeurope", "Standard_D2s_v5", "/sub/vm"]],
        )
        mock_azure_clients.graph.resources.return_value = vm_resp
        mock_azure_clients.monitor = MagicMock()
        result = find_underutilized_vms.func(10.0)
        assert "No VMs" in result


class TestFindExpensiveResources:
    def test_finds_cosmos_db(self, mock_azure_clients) -> None:
        cosmos_resp = _mock_graph_response(
            [
                "name",
                "resourceGroup",
                "location",
                "writeLocations",
                "readLocations",
                "multiWrite",
                "id",
            ],
            [["cosmos-prod", "rg-prod", "westeurope", "2", "3", "true", "/sub/cosmos"]],
        )
        # expensive: cosmos, AKS, redis, LAW, SB, EH, FW, bastion, ACR, DBX
        mock_azure_clients.graph.resources.side_effect = [
            cosmos_resp,
            *_empties(9),
        ]
        result = find_expensive_resources.func()
        assert "cosmos-prod" in result

    def test_finds_firewalls(self, mock_azure_clients) -> None:
        fw_resp = _mock_graph_response(
            ["name", "resourceGroup", "location", "sku", "tier", "id"],
            [["fw-prod", "rg-prod", "westeurope", "AZFW_VNet", "Standard", "/sub/fw"]],
        )
        mock_azure_clients.graph.resources.side_effect = [
            *_empties(6),  # cosmos, AKS, redis, LAW, SB, EH
            fw_resp,  # FW
            *_empties(3),  # bastion, ACR, DBX
        ]
        result = find_expensive_resources.func()
        assert "fw-prod" in result
        assert "$912" in result

    def test_all_empty(self, mock_azure_clients) -> None:
        mock_azure_clients.graph.resources.side_effect = _empties(10)
        result = find_expensive_resources.func()
        assert "none found" in result.lower()
