FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml requirements.txt ./
RUN pip install -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY run_mcp.py ./

RUN mkdir -p /data && \
    addgroup --system app && adduser --system --ingroup app app && \
    chown -R app:app /app /data
USER app

ENV OPENLEDGER_DB=/data/openledger.db \
    MCP_TRANSPORT=sse \
    MCP_PORT=8791

EXPOSE 8791

# Seed a fresh DB on first boot if none exists, then start the MCP server (SSE).
CMD ["sh", "-c", "[ -f \"$OPENLEDGER_DB\" ] || python scripts/seed.py; python -m src.mcp_server"]
