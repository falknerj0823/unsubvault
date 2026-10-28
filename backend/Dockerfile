FROM python:3.12-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Optional: Claude Code / Codex CLIs for subscription-based LLM access (docker compose build --build-arg INSTALL_AI_CLIS=true)
ARG INSTALL_AI_CLIS=false
RUN if [ "$INSTALL_AI_CLIS" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends nodejs npm \
      && npm install -g @anthropic-ai/claude-code@2.1.309 @openai/codex@0.165.0 \
      && rm -rf /var/lib/apt/lists/* /root/.npm; \
    fi
COPY . .
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
