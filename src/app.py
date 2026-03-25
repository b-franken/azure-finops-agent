"""Chainlit chat UI for the LangGraph Azure Cost Agent."""

from __future__ import annotations

import logging
import os
import uuid

import chainlit as cl

from src.config import config as agent_config
from src.workflow import create_graph

logger = logging.getLogger("azure-cost-agent")

_HANDOFF_MARKERS = (
    "transferred to",
    "transferring to",
    "transferring back",
    "successfully transferred",
)


def _is_handoff_message(content: str) -> bool:
    lower = content.strip().lower()
    return any(marker in lower for marker in _HANDOFF_MARKERS)


_tracer = None


def _create_tracer():
    conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn_str:
        return None
    try:
        from langchain_azure_ai.callbacks.tracers import AzureAIOpenTelemetryTracer

        return AzureAIOpenTelemetryTracer(
            connection_string=conn_str,
            enable_content_recording=os.getenv(
                "ENABLE_CONTENT_RECORDING", "false"
            ).lower()
            == "true",
            name="azure-cost-agent-langgraph",
        )
    except ImportError:
        logger.warning("langchain-azure-ai not installed — tracing disabled")
        return None


@cl.on_chat_start
async def start():
    global _tracer
    _tracer = _create_tracer()

    graph = create_graph()
    thread_id = str(uuid.uuid4())
    cl.user_session.set("graph", graph)
    cl.user_session.set("thread_id", thread_id)

    await cl.Message(
        content="Ask me about your Azure costs, waste, budgets, tags, "
        "or generate a full optimization report.",
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    if len(message.content) > agent_config.max_input_length:
        await cl.Message(
            content=f"Input too long ({len(message.content)} chars). "
            f"Maximum is {agent_config.max_input_length}.",
        ).send()
        return

    graph = cl.user_session.get("graph")
    thread_id = cl.user_session.get("thread_id")

    msg = cl.Message(content="")
    await msg.send()

    config = {"configurable": {"thread_id": thread_id}}
    if _tracer:
        config["callbacks"] = [_tracer]

    try:
        async for event in graph.astream(
            {"messages": [{"role": "user", "content": message.content}]},
            config=config,
            stream_mode="updates",
        ):
            for node_name, node_output in event.items():
                if node_name == "supervisor":
                    continue
                for m in node_output.get("messages", []):
                    if not hasattr(m, "content") or not m.content:
                        continue
                    if getattr(m, "tool_calls", None):
                        continue
                    if _is_handoff_message(m.content):
                        continue
                    await msg.stream_token(m.content)
    except Exception:
        logger.exception("Agent run failed")
        msg.content = "Something went wrong. Please try again."

    if not msg.content:
        msg.content = "No response received. Please try again."

    await msg.update()
