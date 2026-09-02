FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

# Keep common SWE-bench Python repositories reproducible offline during agent
# reproduction checks. The agent container has no network at runtime.
RUN python -m pip install --no-cache-dir "mpmath==1.3.0" "pytest==8.3.5"
