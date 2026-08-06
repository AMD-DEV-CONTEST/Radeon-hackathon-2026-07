# Track 3 (Physical AI) submission image — full env for reproducibility on AMD Radeon.
# Canonical image. Base: ROCm 6.2 + Ubuntu 22.04 + Python 3.10 + PyTorch 2.3.0
# (verified tag on Docker Hub). The reference run instance used ROCm 7.2.1 /
# torch 2.9.1+HIP — see requirements-lock.txt; on a ROCm 7.x host swap the base
# tag to the matching rocm/pytorch image before building.
FROM rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_release_2.3.0

WORKDIR /app

# Install Genesis + RL deps (torch comes from the base ROCm image).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source.
COPY . .

# JupyterLab for Radeon Cloud "Open Notebook" access.
# Bound to 0.0.0.0 so the Radeon Cloud proxy can reach it, but a token is
# always required: set JUPYTER_TOKEN at runtime (see README).  If it is not
# set, a strong random token is generated on start and printed in the
# container log ("?token=...").
RUN pip install --no-cache-dir jupyter

# Run as non-root (least privilege); /app stays writable for notebooks.
RUN useradd --create-home --uid 1000 runner && chown -R runner:runner /app
USER runner

EXPOSE 8888
CMD ["sh", "-c", "exec jupyter lab --ip=0.0.0.0 --no-browser --ServerApp.token=${JUPYTER_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"]
