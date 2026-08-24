FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

# Install official Node.js 22 LTS, gosu for safe privilege drop, and packages
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg gosu \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g express@5.0.1 supertest \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH="/app"
ENV NODE_PATH="/usr/lib/node_modules:/usr/local/lib/node_modules"

# Create non-root user
RUN groupadd -r synapse && useradd -r -g synapse synapse

COPY --from=builder /install /usr/local
COPY . .

# Ensure entrypoint is executable
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
