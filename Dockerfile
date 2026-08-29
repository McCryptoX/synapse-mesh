FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

# Install Node.js 22 LTS, Rust toolchain, and exact runtime packages.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg rustc cargo \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g express@5.0.1 supertest@7.0.0 typescript@5.7.3 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH="/app"
ENV NODE_PATH="/usr/lib/node_modules:/usr/local/lib/node_modules"
ENV PYTHONDONTWRITEBYTECODE="1"
ENV PYTHONUNBUFFERED="1"

# Create non-root user
RUN groupadd --gid 10001 synapse && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin synapse

COPY --from=builder /install /usr/local

# Copy only production runtime material. Repository reviews, prompts, reports,
# screenshots, local databases, and deployment credentials never enter the image.
COPY docker-entrypoint.sh ./docker-entrypoint.sh
COPY app ./app
RUN mkdir -p ./scripts ./bundles/drafts ./data ./evidence/runs ./evidence/lifecycle \
    && chown -R synapse:synapse ./bundles/drafts ./data
COPY scripts/github_harvester.py scripts/synapse_reverify.py scripts/run_autonomous_pipeline.py scripts/install.sh ./scripts/
COPY bundles/golden ./bundles/golden
COPY evidence/runs ./evidence/runs
COPY evidence/lifecycle ./evidence/lifecycle

# Ensure entrypoint is executable
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

USER 10001:10001

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
