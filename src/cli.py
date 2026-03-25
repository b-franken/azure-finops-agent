"""Interactive CLI for the Azure Cost Agent."""

from __future__ import annotations

import asyncio
import uuid

from dotenv import load_dotenv

from src.config import config as agent_config
from src.workflow import create_graph


async def main() -> None:
    load_dotenv()
    graph = create_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("Azure Cost Agent (LangGraph)")
    print("Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input or user_input.lower() in ("quit", "exit"):
            break

        if len(user_input) > agent_config.max_input_length:
            limit = agent_config.max_input_length
            print(f"Input too long. Maximum is {limit} characters.")
            continue

        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": user_input}]},
            config=config,
        )
        response = result["messages"][-1].content
        print(f"\nAgent: {response}\n")


if __name__ == "__main__":
    asyncio.run(main())
