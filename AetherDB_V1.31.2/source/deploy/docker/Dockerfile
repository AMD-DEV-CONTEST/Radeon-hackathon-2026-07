# syntax=docker/dockerfile:1.7
ARG PYTHON_BASE_IMAGE=python:3.10.18-slim-bookworm

FROM ${PYTHON_BASE_IMAGE} AS wheels
WORKDIR /build
COPY requirements.txt .
RUN python -m pip wheel --disable-pip-version-check --no-cache-dir \
    --wheel-dir /wheels -r requirements.txt

FROM ${PYTHON_BASE_IMAGE} AS runtime
ARG AETHERDB_VERSION=1.31.2
LABEL org.opencontainers.image.title="AetherDB Core" \
      org.opencontainers.image.version="${AETHERDB_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/aetherdb \
    AETHERDB_RESOURCE_ROOT=/opt/aetherdb \
    AETHERDB_RUNTIME_ROOT=/var/lib/aetherdb \
    WORLDVIEW_CORS=container

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 aetherdb \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin aetherdb

COPY --from=wheels /wheels /wheels
RUN python -m pip install --disable-pip-version-check --no-cache-dir /wheels/* \
    && rm -rf /wheels

WORKDIR /opt/aetherdb
COPY --chown=aetherdb:aetherdb . .
RUN test ! -e /opt/aetherdb/config.yaml \
    && test ! -e /opt/aetherdb/config.local.yaml \
    && mkdir -p /var/lib/aetherdb /models \
    && chown -R aetherdb:aetherdb /var/lib/aetherdb /models

USER aetherdb
WORKDIR /var/lib/aetherdb
VOLUME ["/var/lib/aetherdb", "/models"]
ENTRYPOINT ["python", "/opt/aetherdb/scripts/container_entrypoint.py"]
