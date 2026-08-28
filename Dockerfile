FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-alpine3.23 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apk upgrade --no-cache \
    && apk add --no-cache poppler-utils curl
WORKDIR /app
COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY receipt_ledger ./receipt_ledger
RUN pip install --no-cache-dir .
COPY --from=frontend /build/frontend/dist ./frontend/dist
RUN adduser -D -u 10001 ledger && mkdir -p /data && chown -R ledger:ledger /data /app
USER ledger
EXPOSE 8080
CMD ["uvicorn", "receipt_ledger.api:app", "--host", "0.0.0.0", "--port", "8080"]

# Provider-named aliases let Compose select the correct worker image directly
# from AI_PROVIDER without a second setting that can drift out of sync.
FROM runtime AS openai
FROM runtime AS anthropic
FROM runtime AS gemini

FROM runtime AS codex
USER root
RUN apk add --no-cache nodejs npm \
    && npm install --global @openai/codex@0.150.1 \
    && npm cache clean --force
USER ledger
