"""Waste Detector agent — finds idle, orphaned, and oversized resources."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

import httpx
from langchain_core.tools import tool
from pydantic import Field

from src.agents._context import get_clients
from src.graph import run_resource_graph_query
from src.pricing import get_monthly_cost

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable


_STOPPED_VMS = """\
resources
| where type == 'microsoft.compute/virtualmachines'
| extend powerState = tostring(
    properties.extended.instanceView.powerState.displayStatus)
| where powerState == 'VM deallocated'
    or powerState == 'VM stopped'
| project name, resourceGroup, location,
    vmSize = tostring(properties.hardwareProfile.vmSize),
    powerState, id
"""

_ORPHANED_DISKS = """\
resources
| where type == 'microsoft.compute/disks'
| where properties.diskState == 'Unattached'
| project name, resourceGroup, location,
    sku = tostring(sku.name),
    sizeGb = tostring(properties.diskSizeGB), id
"""

_ORPHANED_NICS = """\
resources
| where type == 'microsoft.network/networkinterfaces'
| where isnull(properties.virtualMachine.id)
    and isnull(properties.privateEndpoint.id)
| project name, resourceGroup, location, id
"""

_ORPHANED_PUBLIC_IPS = """\
resources
| where type == 'microsoft.network/publicipaddresses'
| where isnull(properties.ipConfiguration.id)
| project name, resourceGroup, location,
    sku = tostring(sku.name), id
"""

_EMPTY_APP_SERVICE_PLANS = """\
resources
| where type == 'microsoft.web/serverfarms'
| where properties.numberOfSites == 0
| project name, resourceGroup, location,
    sku = tostring(sku.name),
    tier = tostring(sku.tier), id
"""

_IDLE_LOAD_BALANCERS = """\
resources
| where type == 'microsoft.network/loadbalancers'
| where array_length(properties.backendAddressPools) == 0
| project name, resourceGroup, location,
    sku = tostring(sku.name), id
"""

_OVERSIZED_SQL_DATABASES = """\
resources
| where type == 'microsoft.sql/servers/databases'
| where name != 'master'
| where sku.tier in ('Premium', 'BusinessCritical')
| project name, resourceGroup, location,
    tier = tostring(sku.tier),
    capacity = tostring(sku.capacity), id
"""

_OVERSIZED_APP_PLANS = """\
resources
| where type == 'microsoft.web/serverfarms'
| where sku.tier in ('PremiumV2', 'PremiumV3', 'Premium')
| project name, resourceGroup, location,
    tier = tostring(sku.tier),
    sku = tostring(sku.name),
    sites = toint(properties.numberOfSites), id
"""

_OLD_SNAPSHOTS = """\
resources
| where type == 'microsoft.compute/snapshots'
| where properties.timeCreated < ago(30d)
| project name, resourceGroup, location,
    sku = tostring(sku.name),
    sizeGb = tostring(properties.diskSizeGB),
    created = tostring(properties.timeCreated), id
"""

_ORPHANED_NAT_GATEWAYS = """\
resources
| where type == 'microsoft.network/natgateways'
| where isnull(properties.subnets) or array_length(properties.subnets) == 0
| project name, resourceGroup, location, id
"""

_IDLE_APP_GATEWAYS = """\
resources
| where type == 'microsoft.network/applicationgateways'
| where array_length(properties.backendAddressPools) == 0
    or array_length(properties.backendAddressPools[0].properties.backendAddresses) == 0
| project name, resourceGroup, location,
    sku = tostring(properties.sku.name), id
"""

_EMPTY_STORAGE_ACCOUNTS = """\
resources
| where type == 'microsoft.storage/storageaccounts'
| project name, resourceGroup, location,
    sku = tostring(sku.name), id
"""

_UNPROTECTED_KEY_VAULTS = """\
resources
| where type == 'microsoft.keyvault/vaults'
| where properties.enableSoftDelete == true
    and properties.enablePurgeProtection != true
| project name, resourceGroup, location, id
"""

_RUNNING_VMS = """\
resources
| where type == 'microsoft.compute/virtualmachines'
| extend powerState = tostring(
    properties.extended.instanceView.powerState.displayStatus)
| where powerState == 'VM running'
| project name, resourceGroup, location,
    vmSize = tostring(properties.hardwareProfile.vmSize), id
"""


# ── Tier 1: Orphan workbook queries ──────────────────────────

_ORPHANED_NSGS = """\
resources
| where type == 'microsoft.network/networksecuritygroups'
| where isnull(properties.networkInterfaces)
    and isnull(properties.subnets)
| project name, resourceGroup, location, id
"""

_ORPHANED_ROUTE_TABLES = """\
resources
| where type == 'microsoft.network/routetables'
| where isnull(properties.subnets)
| project name, resourceGroup, location, id
"""

_DISCONNECTED_PRIVATE_ENDPOINTS = """\
resources
| where type == 'microsoft.network/privateendpoints'
| extend connection = iff(
    array_length(properties.manualPrivateLinkServiceConnections) > 0,
    properties.manualPrivateLinkServiceConnections[0],
    properties.privateLinkServiceConnections[0])
| extend stateEnum = tostring(
    connection.properties.privateLinkServiceConnectionState.status)
| where stateEnum == 'Disconnected'
| project name, resourceGroup, location, id
"""

_ORPHANED_PRIVATE_DNS_ZONES = """\
resources
| where type == 'microsoft.network/privatednszones'
| where properties.numberOfVirtualNetworkLinks == 0
| project name, resourceGroup, location, id
"""

_EMPTY_AVAILABILITY_SETS = """\
resources
| where type == 'microsoft.compute/availabilitysets'
| where properties.virtualMachines == '[]'
| where not(name endswith '-asr')
| project name, resourceGroup, location, id
"""

_SQL_ELASTIC_POOLS = """\
resources
| where type == 'microsoft.sql/servers/elasticpools'
| project name, resourceGroup, location,
    sku = tostring(sku.name),
    tier = tostring(sku.tier), id
"""

_VNET_GATEWAYS = """\
resources
| where type == 'microsoft.network/virtualnetworkgateways'
| project name, resourceGroup, location,
    gatewayType = tostring(properties.gatewayType),
    sku = tostring(properties.sku.name), id
"""

_VNET_GATEWAY_CONNECTIONS = """\
resources
| where type == 'microsoft.network/connections'
| project name,
    gwId = tolower(tostring(
        properties.virtualNetworkGateway1.id))
"""

_EXPIRED_CERTIFICATES = """\
resources
| where type == 'microsoft.web/certificates'
| extend expiresOn = todatetime(properties.expirationDate)
| where expiresOn <= now()
| project name, resourceGroup, location,
    expiresOn = tostring(properties.expirationDate), id
"""

_ORPHANED_FRONTDOOR_WAF = """\
resources
| where type == 'microsoft.network/frontdoorwebapplicationfirewallpolicies'
| where properties.securityPolicyLinks == '[]'
| project name, resourceGroup, location,
    sku = tostring(sku.name), id
"""

_ORPHANED_TRAFFIC_MANAGER = """\
resources
| where type == 'microsoft.network/trafficmanagerprofiles'
| where properties.endpoints == '[]'
| project name, resourceGroup, location, id
"""

# ── Tier 2: Expensive always-on services ─────────────────────

_COSMOS_DB_ACCOUNTS = """\
resources
| where type == 'microsoft.documentdb/databaseaccounts'
| extend writeLocations = array_length(properties.writeLocations)
| extend readLocations = array_length(properties.readLocations)
| extend multiWrite = tostring(
    properties.enableMultipleWriteLocations)
| project name, resourceGroup, location,
    writeLocations, readLocations, multiWrite, id
"""

_AKS_NODE_POOLS = """\
resources
| where type == 'microsoft.containerservice/managedclusters'
| extend nodePool = properties.agentPoolProfiles
| mv-expand nodePool
| extend poolName = tostring(nodePool.name)
| extend vmSize = tostring(nodePool.vmSize)
| extend nodeCount = tostring(nodePool.['count'])
| extend powerState = tostring(nodePool.powerState.code)
| project name, resourceGroup, location,
    poolName, vmSize, nodeCount, powerState, id
"""

_REDIS_INSTANCES = """\
resources
| where type == 'microsoft.cache/redis'
    or type == 'microsoft.cache/redisenterprise'
| project name, resourceGroup, location,
    sku = tostring(sku.name),
    capacity = tostring(sku.capacity), id
"""

_LOG_ANALYTICS_HIGH_RETENTION = """\
resources
| where type == 'microsoft.operationalinsights/workspaces'
| extend retentionDays = toint(properties.retentionInDays)
| extend skuName = tostring(properties.sku.name)
| where retentionDays > 30
| project name, resourceGroup, location,
    skuName, retentionDays = tostring(retentionDays), id
"""

_SERVICE_BUS_NAMESPACES = """\
resources
| where type == 'microsoft.servicebus/namespaces'
| project name, resourceGroup, location,
    sku = tostring(sku.name),
    tier = tostring(sku.tier), id
"""

_EVENT_HUB_NAMESPACES = """\
resources
| where type == 'microsoft.eventhub/namespaces'
| project name, resourceGroup, location,
    sku = tostring(sku.name),
    tier = tostring(sku.tier),
    capacity = tostring(sku.capacity), id
"""

_AZURE_FIREWALLS = """\
resources
| where type == 'microsoft.network/azurefirewalls'
| project name, resourceGroup, location,
    sku = tostring(properties.sku.name),
    tier = tostring(properties.sku.tier), id
"""

_BASTION_HOSTS = """\
resources
| where type == 'microsoft.network/bastionhosts'
| project name, resourceGroup, location,
    sku = tostring(properties.sku.name), id
"""

_DDOS_PROTECTION_PLANS = """\
resources
| where type == 'microsoft.network/ddosprotectionplans'
| where isnull(properties.virtualNetworks)
| project name, resourceGroup, location, id
"""

_CONTAINER_REGISTRIES = """\
resources
| where type == 'microsoft.containerregistry/registries'
| project name, resourceGroup, location,
    sku = tostring(sku.name), id
"""

_DATABRICKS_WORKSPACES = """\
resources
| where type == 'microsoft.databricks/workspaces'
| project name, resourceGroup, location,
    sku = tostring(sku.name), id
"""


def _estimate_cost(
    sku_name: str,
    region: str,
    service_name: str = "Virtual Machines",
) -> float | None:
    try:
        return get_monthly_cost(sku_name, region, service_name)
    except (httpx.HTTPError, ValueError, KeyError):
        logger.debug("Cost lookup failed for %s in %s", sku_name, region)
        return None


def _format_with_cost(
    label: str,
    rows: list[dict[str, str]],
    cost_fn: Callable[..., float | None] | None = None,
) -> tuple[str, float]:
    if not rows:
        return f"{label}: none found.", 0.0

    total_cost = 0.0
    lines = [f"{label} ({len(rows)}):\n"]

    for row in rows:
        name = row.get("name", "unknown")
        rg = row.get("resourceGroup", "")
        loc = row.get("location", "")

        extras = [
            f"{k}={v}"
            for k, v in row.items()
            if k not in {"name", "resourceGroup", "location", "subscriptionId", "id"}
            and v
        ]

        cost = cost_fn(row) if cost_fn else None
        if cost:
            total_cost += cost
            extras.append(f"~${cost:.2f}/mo")

        extra = f" ({', '.join(extras)})" if extras else ""
        lines.append(f"  - {name} [{rg}, {loc}]{extra}")

    if total_cost > 0:
        lines.append(f"\n  Subtotal: ~${total_cost:.2f}/mo")

    return "\n".join(lines), total_cost


def _vm_cost(row: dict[str, str]) -> float | None:
    return _estimate_cost(
        row.get("vmSize", ""),
        row.get("location", ""),
    )


def _disk_cost(row: dict[str, str]) -> float | None:
    return _estimate_cost(
        row.get("sku", ""),
        row.get("location", ""),
        "Storage",
    )


def _public_ip_cost(row: dict[str, str]) -> float | None:
    return _estimate_cost(
        row.get("sku", "Standard"),
        row.get("location", ""),
        "Virtual Network",
    )


@tool
def find_idle_resources() -> str:
    """Find stopped VMs, empty plans, idle LBs/gateways, and more."""
    clients = get_clients()

    vms_text, vms_cost = _format_with_cost(
        "Stopped/deallocated VMs",
        run_resource_graph_query(clients, _STOPPED_VMS),
        _vm_cost,
    )
    plans_text, plans_cost = _format_with_cost(
        "Empty App Service plans",
        run_resource_graph_query(clients, _EMPTY_APP_SERVICE_PLANS),
    )
    lbs_text, lbs_cost = _format_with_cost(
        "Idle load balancers",
        run_resource_graph_query(clients, _IDLE_LOAD_BALANCERS),
    )
    appgw_text, _ = _format_with_cost(
        "Idle Application Gateways",
        run_resource_graph_query(clients, _IDLE_APP_GATEWAYS),
    )
    avset_text, _ = _format_with_cost(
        "Empty Availability Sets",
        run_resource_graph_query(clients, _EMPTY_AVAILABILITY_SETS),
    )
    ddos_text, _ = _format_with_cost(
        "DDoS Protection Plans without VNets (~$2944/mo each)",
        run_resource_graph_query(clients, _DDOS_PROTECTION_PLANS),
    )

    # VNet gateways without connections
    gateways = run_resource_graph_query(clients, _VNET_GATEWAYS)
    connections = run_resource_graph_query(clients, _VNET_GATEWAY_CONNECTIONS)
    connected_gw_ids = {c.get("gwId", "").lower() for c in connections}
    orphaned_gws = [
        gw for gw in gateways if gw.get("id", "").lower() not in connected_gw_ids
    ]
    gw_text, _ = _format_with_cost(
        "VNet Gateways without connections",
        orphaned_gws,
    )

    total = vms_cost + plans_cost + lbs_cost
    parts = [
        vms_text,
        plans_text,
        lbs_text,
        appgw_text,
        avset_text,
        gw_text,
        ddos_text,
    ]
    if total > 0:
        parts.append(f"Total idle resource cost: ~${total:.2f}/mo")

    return "\n\n".join(parts)


@tool
def find_orphaned_resources() -> str:
    """Find orphaned disks, NICs, IPs, NSGs, and more."""
    clients = get_clients()

    disks_text, disks_cost = _format_with_cost(
        "Orphaned disks",
        run_resource_graph_query(clients, _ORPHANED_DISKS),
        _disk_cost,
    )
    nics_text, _ = _format_with_cost(
        "Orphaned NICs",
        run_resource_graph_query(clients, _ORPHANED_NICS),
    )
    ips_text, ips_cost = _format_with_cost(
        "Orphaned public IPs",
        run_resource_graph_query(clients, _ORPHANED_PUBLIC_IPS),
        _public_ip_cost,
    )
    nat_text, _ = _format_with_cost(
        "Orphaned NAT Gateways",
        run_resource_graph_query(clients, _ORPHANED_NAT_GATEWAYS),
    )
    snap_text, snap_cost = _format_with_cost(
        "Old snapshots (>30 days)",
        run_resource_graph_query(clients, _OLD_SNAPSHOTS),
        _disk_cost,
    )
    nsg_text, _ = _format_with_cost(
        "Orphaned NSGs (no NIC/subnet)",
        run_resource_graph_query(clients, _ORPHANED_NSGS),
    )
    rt_text, _ = _format_with_cost(
        "Orphaned Route Tables (no subnet)",
        run_resource_graph_query(clients, _ORPHANED_ROUTE_TABLES),
    )
    pe_text, _ = _format_with_cost(
        "Disconnected Private Endpoints",
        run_resource_graph_query(clients, _DISCONNECTED_PRIVATE_ENDPOINTS),
    )
    dns_text, _ = _format_with_cost(
        "Orphaned Private DNS Zones (no VNet links)",
        run_resource_graph_query(clients, _ORPHANED_PRIVATE_DNS_ZONES),
    )
    fdwaf_text, _ = _format_with_cost(
        "Orphaned Front Door WAF Policies",
        run_resource_graph_query(clients, _ORPHANED_FRONTDOOR_WAF),
    )
    tm_text, _ = _format_with_cost(
        "Orphaned Traffic Manager Profiles (no endpoints)",
        run_resource_graph_query(clients, _ORPHANED_TRAFFIC_MANAGER),
    )

    total = disks_cost + ips_cost + snap_cost
    parts = [
        disks_text,
        nics_text,
        ips_text,
        nat_text,
        snap_text,
        nsg_text,
        rt_text,
        pe_text,
        dns_text,
        fdwaf_text,
        tm_text,
    ]
    if total > 0:
        parts.append(f"Total orphaned resource cost: ~${total:.2f}/mo")

    return "\n\n".join(parts)


@tool
def find_oversized_resources() -> str:
    """Find Premium databases, elastic pools, and Premium App Service plans."""
    clients = get_clients()

    dbs_text, _ = _format_with_cost(
        "Premium/BusinessCritical SQL databases",
        run_resource_graph_query(clients, _OVERSIZED_SQL_DATABASES),
    )
    plans_text, _ = _format_with_cost(
        "Premium App Service plans",
        run_resource_graph_query(clients, _OVERSIZED_APP_PLANS),
    )
    pools_text, _ = _format_with_cost(
        "SQL Elastic Pools (review for usage)",
        run_resource_graph_query(clients, _SQL_ELASTIC_POOLS),
    )

    return "\n\n".join([dbs_text, plans_text, pools_text])


@tool
def find_stale_resources() -> str:
    """Find unused storage, Key Vaults, and expired certs."""
    clients = get_clients()

    storage_text, _ = _format_with_cost(
        "Storage accounts (review for usage)",
        run_resource_graph_query(clients, _EMPTY_STORAGE_ACCOUNTS),
    )
    kv_text, _ = _format_with_cost(
        "Key Vaults with soft-delete but no purge protection",
        run_resource_graph_query(clients, _UNPROTECTED_KEY_VAULTS),
    )
    cert_text, _ = _format_with_cost(
        "Expired certificates",
        run_resource_graph_query(clients, _EXPIRED_CERTIFICATES),
    )

    return "\n\n".join([storage_text, kv_text, cert_text])


@tool
def find_underutilized_vms(
    cpu_threshold: Annotated[
        float,
        Field(description="CPU % threshold — VMs below this are underutilized"),
    ] = 10.0,
) -> str:
    """Find running VMs with average CPU below the threshold and show monthly cost."""
    clients = get_clients()
    monitor = clients.monitor
    if monitor is None:
        return "Monitor client not configured — cannot check CPU metrics."

    from src.metrics import get_avg_cpu

    vms = run_resource_graph_query(clients, _RUNNING_VMS)
    if not vms:
        return "No running VMs found."

    underutilized: list[str] = []
    total_cost = 0.0

    for vm in vms:
        resource_id = vm.get("id", "")
        if not resource_id:
            continue
        avg_cpu = get_avg_cpu(monitor, resource_id)
        if avg_cpu is not None and avg_cpu < cpu_threshold:
            name = vm.get("name", "unknown")
            size = vm.get("vmSize", "unknown")
            rg = vm.get("resourceGroup", "")
            cost = _vm_cost(vm)
            cost_str = f", ~${cost:.2f}/mo" if cost else ""
            if cost:
                total_cost += cost
            underutilized.append(
                f"  - {name} [{rg}] — {size}, avg CPU: {avg_cpu}%{cost_str}",
            )

    if not underutilized:
        return f"No VMs with avg CPU below {cpu_threshold}% found."

    header = f"Underutilized VMs (avg CPU < {cpu_threshold}%, last 30 days):\n"
    result = header + "\n".join(underutilized)
    if total_cost > 0:
        result += f"\n\nTotal underutilized VM cost: ~${total_cost:.2f}/mo"
    return result


@tool
def find_expensive_resources() -> str:
    """Find expensive always-on resources for cost review."""
    clients = get_clients()

    cosmos_text, _ = _format_with_cost(
        "Cosmos DB accounts (review RU provisioning)",
        run_resource_graph_query(clients, _COSMOS_DB_ACCOUNTS),
    )
    aks_text, _ = _format_with_cost(
        "AKS node pools",
        run_resource_graph_query(clients, _AKS_NODE_POOLS),
    )
    redis_text, _ = _format_with_cost(
        "Redis Cache instances",
        run_resource_graph_query(clients, _REDIS_INSTANCES),
    )
    law_text, _ = _format_with_cost(
        "Log Analytics workspaces (retention >30 days)",
        run_resource_graph_query(clients, _LOG_ANALYTICS_HIGH_RETENTION),
    )
    sb_text, _ = _format_with_cost(
        "Service Bus namespaces",
        run_resource_graph_query(clients, _SERVICE_BUS_NAMESPACES),
    )
    eh_text, _ = _format_with_cost(
        "Event Hub namespaces",
        run_resource_graph_query(clients, _EVENT_HUB_NAMESPACES),
    )
    fw_text, _ = _format_with_cost(
        "Azure Firewalls (always-on, ~$912/mo each)",
        run_resource_graph_query(clients, _AZURE_FIREWALLS),
    )
    bastion_text, _ = _format_with_cost(
        "Bastion Hosts (always-on, ~$140/mo each)",
        run_resource_graph_query(clients, _BASTION_HOSTS),
    )
    acr_text, _ = _format_with_cost(
        "Container Registries",
        run_resource_graph_query(clients, _CONTAINER_REGISTRIES),
    )
    dbx_text, _ = _format_with_cost(
        "Databricks workspaces",
        run_resource_graph_query(clients, _DATABRICKS_WORKSPACES),
    )

    parts = [
        cosmos_text,
        aks_text,
        redis_text,
        law_text,
        sb_text,
        eh_text,
        fw_text,
        bastion_text,
        acr_text,
        dbx_text,
    ]
    return "\n\n".join(parts)
