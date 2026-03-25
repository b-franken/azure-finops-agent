FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uv \
    && useradd -m agent \
    && chown agent:agent /app

USER agent

COPY --chown=agent pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY --chown=agent src/ src/
COPY --chown=agent prompts/ prompts/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000')"

CMD ["uv", "run", "chainlit", "run", "src/app.py", "--host", "0.0.0.0", "--port", "8000"]
