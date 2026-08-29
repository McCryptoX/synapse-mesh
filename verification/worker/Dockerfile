# syntax=docker/dockerfile:1.7
FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2

ARG BUNDLE_PATH
ARG REQUIREMENTS_LOCK
ARG SOURCE_REVISION

ENV HOME="/work" \
    LANG="C.UTF-8" \
    PATH="/usr/local/bin:/usr/bin:/bin" \
    PYTHONDONTWRITEBYTECODE="1" \
    PYTHONHASHSEED="0" \
    PYTHONUNBUFFERED="1" \
    TZ="UTC"

COPY ${REQUIREMENTS_LOCK} /runner/requirements.lock
RUN python -m pip install --disable-pip-version-check --no-cache-dir --no-deps \
        --require-hashes -r /runner/requirements.lock \
    && python -m pip check

COPY verification/worker/verify_bundle.py /runner/verify_bundle.py
COPY ${BUNDLE_PATH} /input/bundle.json

RUN install -d -m 0700 -o 10001 -g 10001 /work /output \
    && test -n "$SOURCE_REVISION"

LABEL org.opencontainers.image.title="Synapse-Mesh disposable trusted-fixture verifier" \
      org.opencontainers.image.revision="$SOURCE_REVISION" \
      dev.synapse.runner.version="synapse-disposable-verifier-v1" \
      dev.synapse.base.image="python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2"

USER 10001:10001
WORKDIR /work

ENTRYPOINT ["python", "/runner/verify_bundle.py"]
CMD ["/input/bundle.json", "/output/raw-report.json"]
