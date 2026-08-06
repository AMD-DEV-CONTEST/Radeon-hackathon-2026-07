#!/usr/bin/env bash
# SpatialForge 3D - environment bootstrap for the AMD Radeon Cloud instance.
# Idempotent: safe to run again after an instance restart.
#
# Assumes: this repo cloned at /persistent/spatialforge, base image
# amd-oneclick-base:rocm7.2.1-py3.12, persistent volume mounted at /persistent.

set -u
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "== SpatialForge setup, repo at ${REPO_DIR} =="

# ---------------------------------------------------------------- 1. TLS trust
# The instance sits behind a TLS-intercepting proxy with a self-signed cert.
# Trust it explicitly rather than disabling verification.
if ! git ls-remote https://github.com/VAST-AI-Research/TripoSR.git >/dev/null 2>&1; then
  echo "-- trusting proxy certificate"
  openssl s_client -showcerts -connect github.com:443 </dev/null 2>/dev/null \
    | openssl x509 -outform PEM > /usr/local/share/ca-certificates/proxy.crt
  CERTIFI=$(/opt/venv/bin/python -c "import certifi; print(certifi.where())")
  cat /usr/local/share/ca-certificates/proxy.crt >> "${CERTIFI}"
  update-ca-certificates >/dev/null 2>&1 || true
else
  echo "-- GitHub reachable, cert trust already in place"
fi

# ------------------------------------------------------------ 2. Session env
cat > /persistent/env.sh << 'EOF'
source /persistent/venv_sg/bin/activate
export SSL_CERT_FILE=$(python -c "import certifi; print(certifi.where())")
export REQUESTS_CA_BUNDLE=$SSL_CERT_FILE
export GIT_SSL_CAINFO=$SSL_CERT_FILE
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/persistent/hf_cache
export PIP_CACHE_DIR=/persistent/pip_cache
export PATH="$HOME/.local/bin:$PATH"
EOF
echo "-- wrote /persistent/env.sh (source it in every new terminal)"

# ------------------------------------------------- 3. Persistent overlay venv
# /opt/venv holds the ROCm torch build but is NOT persistent. Overlay it.
if [ ! -d /persistent/venv_sg ]; then
  echo "-- creating overlay venv"
  /opt/venv/bin/python -m venv --system-site-packages /persistent/venv_sg
  echo "/opt/venv/lib/python3.12/site-packages" \
    > /persistent/venv_sg/lib/python3.12/site-packages/_base.pth
fi
source /persistent/env.sh
python -c "import torch; assert torch.cuda.is_available(), 'GPU not visible'; print('-- torch', torch.__version__, 'GPU OK')"

# ----------------------------------------------------------------- 4. TripoSR
if [ ! -d /persistent/TripoSR ]; then
  echo "-- cloning TripoSR"
  git clone https://github.com/VAST-AI-Research/TripoSR.git /persistent/TripoSR
fi
pip install -q -r /persistent/TripoSR/requirements.txt onnxruntime
pip uninstall -q -y cupy-cuda12x 2>/dev/null || true   # CUDA-only, breaks rembg on AMD

# ----------------------------------------------------------------- 5. TripoSG
if [ ! -d /persistent/TripoSG ]; then
  echo "-- cloning TripoSG"
  git clone https://github.com/VAST-AI-Research/TripoSG.git /persistent/TripoSG
fi
# numpy==1.22.3 cannot build on Python 3.12; diso is CUDA-only (see patch)
grep -v -E "numpy==1.22.3|^diso" /persistent/TripoSG/requirements.txt > /tmp/req_sg.txt
echo "transformers<5" >> /tmp/req_sg.txt
pip install -q -r /tmp/req_sg.txt
pip install -q -U scikit-image scipy trimesh imageio imageio-ffmpeg

echo "-- applying ROCm patch (diso -> CPU marching cubes)"
( cd /persistent/TripoSG && python "${REPO_DIR}/patch_triposg.py" )

# ------------------------------------------------------------------- 6. u2net
# Normally fetched from GitHub release assets, which are blocked here.
mkdir -p /root/.u2net
if [ ! -f /root/.u2net/u2net.onnx ]; then
  echo "-- fetching u2net via HF mirror"
  python - << 'PY'
from huggingface_hub import hf_hub_download
import shutil
p = hf_hub_download(repo_id="tomjackson2023/rembg", filename="u2net.onnx")
shutil.copy(p, "/root/.u2net/u2net.onnx")
PY
fi

# -------------------------------------------------------------------- 7. done
python - << 'PY'
import torch, trimesh, rembg, diffusers, skimage, scipy
print("== SETUP COMPLETE ==")
print("torch", torch.__version__, "| GPU", torch.cuda.is_available())
PY
cat << 'EOF'

Next:
  source /persistent/env.sh
  python spatialforge_app.py          # UI on http://127.0.0.1:7860
Optional public URL:
  /var/run/secrets/frp-self-service/install
  rc-tunnel expose --port 7860
Benchmark:
  python sf_bench.py --warmup
EOF
