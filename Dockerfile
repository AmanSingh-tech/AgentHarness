# AgentGuard: API + dashboard (+ MCP / HTTP gateway) in one image.
#   docker compose up        -> http://localhost:8000

FROM node:20-bookworm-slim AS dashboard
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    AGENTGUARD_DB_URL=sqlite:////data/agentguard.db \
    AGENTGUARD_DASHBOARD_DIST=/app/dashboard/dist
WORKDIR /app
COPY pyproject.toml README.md ./
COPY agentguard/ agentguard/
RUN pip install --no-cache-dir ".[llm,langgraph,mcp,server]"
COPY --from=dashboard /dashboard/dist /app/dashboard/dist
RUN useradd --create-home agentguard && mkdir -p /data /app/reports && chown agentguard /data /app/reports
USER agentguard
VOLUME ["/data", "/app/reports"]
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/harnesses')"
CMD ["agentguard", "serve", "--host", "0.0.0.0", "--port", "8000", "--reports", "/app/reports"]
