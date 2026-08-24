FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

# Install Node.js runtime for multi-ecosystem sandbox execution
RUN apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r synapse && useradd -r -g synapse synapse

COPY --from=builder /install /usr/local
COPY . .

# Ensure data directory exists and has proper permissions
RUN mkdir -p /app/data && chown -R synapse:synapse /app

USER synapse

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
