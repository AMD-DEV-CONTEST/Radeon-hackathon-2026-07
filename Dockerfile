# ──────────────────────────────────────────────────────────────────────────
# MKO Universal AI Agents — Dockerfile (AMD Radeon Hackathon Track 2)
#
# Base: rocm/pytorch:rocm6.2 on Ubuntu 22.04, Python 3.10, PyTorch with HIP.
#   • rocm6.2  — support for RDNA3 (RX 7000 / RX 9070) out of the box.
#   • Ubuntu 22.04 — most stable glibc / ROCm-host-kernel pair for now.
#   • PyTorch pre-installed — the GPU benchmark endpoint imports torch and
#     can call torch.hip.* at runtime; no extra torch wheels to download.
# ──────────────────────────────────────────────────────────────────────────
FROM rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_2.3.0

# Locale fix — some ROCm helper scripts assume UTF-8.
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# curl for the HEALTHCHECK; strip apt cache to keep the image small.
# Versions pinned to satisfy Hadolint DL3008 ("Pin versions in apt-get
# install"). These are the security-updated versions of curl / ca-certs
# shipping in jammy-updates as of late 2025. Update via Dependabot or a
# manual bump when the rocm/pytorch base image moves to a newer Ubuntu.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl=7.81.0-1ubuntu1.20 \
      ca-certificates=20230311ubuntu0.22.04.1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer dependencies FIRST so source-only changes don't bust the pip cache.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the app source. .dockerignore keeps this minimal.
COPY . .

EXPOSE 49239

# Cheap endpoint that works in demo mode (no API keys) — fine for liveness.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:49239/api/agents || exit 1

# Bind to all interfaces inside the container. run.py reads MKO_HOST and
# defaults to 127.0.0.1 — for local Windows dev. docker-compose overrides
# MKO_HOST=0.0.0.0 below.
ENV MKO_HOST=0.0.0.0 \
    MKO_PORT=49239

# Run as the foreground PID so `docker compose stop` and SIGTERM work normally.
CMD ["python", "run.py"]
