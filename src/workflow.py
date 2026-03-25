"""LangGraph workflow — multi-agent cost optimizer with supervisor routing."""

from __future__ import annotations

import os

from azure.identity import (
    AzureCliCredential,
    ManagedIdentityCredential,
    get_bearer_token_provider,
)
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph_supervisor import create_supervisor

from src.agents.advisor import (
    compare_sku_pricing,
    get_prioritized_recommendations,
    get_reservation_coverage,
    get_reservation_recommendations,
)
from src.agents.anomaly_detector import detect_anomalies, get_daily_trend
from src.agents.budget_tracker import get_budget_forecast, get_budget_status
from src.agents.cost_analyzer import (
    compare_periods,
    export_cost_diff,
    query_costs,
    top_spenders,
)
from src.agents.reporter import generate_report
from src.agents.tag_analyzer import (
    find_resources_missing_tag,
    find_untagged_resources,
    tag_coverage_report,
)
from src.agents.waste_detector import (
    find_expensive_resources,
    find_idle_resources,
    find_orphaned_resources,
    find_oversized_resources,
    find_stale_resources,
    find_underutilized_vms,
)
from src.prompts import load_prompt


def _create_llm() -> AzureChatOpenAI:
    load_dotenv()
    endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    if not endpoint:
        msg = "Set AZURE_AI_PROJECT_ENDPOINT in .env"
        raise ValueError(msg)
    deployment = os.getenv("AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME", "gpt-4.1-mini")

    client_id = os.getenv("AZURE_CLIENT_ID")
    if client_id:
        credential = ManagedIdentityCredential(client_id=client_id)
    else:
        credential = AzureCliCredential()

    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )

    return AzureChatOpenAI(
        azure_endpoint=endpoint,
        azure_deployment=deployment,
        azure_ad_token_provider=token_provider,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-03-01-preview"),
    )


AGENTS_CONFIG = [
    {
        "name": "cost-analyzer",
        "tools": [query_costs, compare_periods, top_spenders, export_cost_diff],
    },
    {
        "name": "waste-detector",
        "tools": [
            find_idle_resources,
            find_orphaned_resources,
            find_oversized_resources,
            find_stale_resources,
            find_underutilized_vms,
            find_expensive_resources,
        ],
    },
    {
        "name": "advisor",
        "tools": [
            get_prioritized_recommendations,
            get_reservation_recommendations,
            get_reservation_coverage,
            compare_sku_pricing,
        ],
    },
    {
        "name": "anomaly-detector",
        "tools": [detect_anomalies, get_daily_trend],
    },
    {
        "name": "budget-tracker",
        "tools": [get_budget_status, get_budget_forecast],
    },
    {
        "name": "tag-analyzer",
        "tools": [
            find_untagged_resources,
            find_resources_missing_tag,
            tag_coverage_report,
        ],
    },
    {
        "name": "reporter",
        "tools": [generate_report],
    },
]


def create_graph():
    """Build the LangGraph supervisor workflow."""
    llm = _create_llm()

    prompts = {cfg["name"]: load_prompt(cfg["name"]) for cfg in AGENTS_CONFIG}

    specialists = [
        create_agent(
            model=llm,
            tools=cfg["tools"],
            name=cfg["name"],
            system_prompt=prompts[cfg["name"]][0],
        )
        for cfg in AGENTS_CONFIG
    ]

    triage_instructions, _ = load_prompt("triage")
    triage_prompt = triage_instructions.format(
        **{f"{name.split('-')[0]}_desc": desc for name, (_, desc) in prompts.items()}
    )

    workflow = create_supervisor(
        specialists,
        model=llm,
        prompt=triage_prompt,
    )

    return workflow.compile(checkpointer=MemorySaver())
