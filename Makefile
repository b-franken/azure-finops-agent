.PHONY: setup run chat test lint format typecheck check docker-build docker-run

setup:
	pip install uv
	uv sync

run:
	uv run python -m src.cli

chat:
	uv run chainlit run src/app.py -w

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src/ --strict

check: lint format typecheck test

docker-build:
	docker build --platform linux/amd64 -t azure-cost-agent-langgraph .

docker-run:
	docker run -p 8000:8000 --env-file .env azure-cost-agent-langgraph
