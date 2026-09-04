#!/usr/bin/env bash
# NuclidePath — AMD/ROCm Preflight Validation
# Run on the Radeon Cloud instance BEFORE anything else.
# Captures: GPU info, ROCm version, device files, PyTorch HIP, disk, versions.
set -euo pipefail

OUTDIR="${1:-/tmp/nuclidepath-preflight}"
mkdir -p "$OUTDIR"
echo "=== NuclidePath AMD Preflight — $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" | tee "$OUTDIR/preflight.log"

log() { echo "--- $1 ---" | tee -a "$OUTDIR/preflight.log"; }

log "GPU / ROCm info"
(rocminfo 2>&1 || echo "rocminfo NOT FOUND") | tee "$OUTDIR/rocminfo.txt" | tail -30
(amd-smi list 2>&1 || rocm-smi 2>&1 || echo "neither amd-smi nor rocm-smi found") | tee "$OUTDIR/gpu-smi.txt"

log "Device files"
ls -la /dev/kfd /dev/dri/render* 2>&1 | tee -a "$OUTDIR/preflight.log"

log "ROCm version"
cat /opt/rocm/.info/version 2>/dev/null || dpkg -l rocm-dev 2>/dev/null | grep rocm || echo "ROCm version unknown" | tee -a "$OUTDIR/preflight.log"

log "PyTorch HIP check"
python3 -c "
import torch
print('torch version:', torch.__version__)
print('HIP available:', torch.cuda.is_available())
print('device count:', torch.cuda.device_count())
if torch.cuda.is_available():
    print('device name:', torch.cuda.get_device_name(0))
    props = torch.cuda.get_device_properties(0)
    total_memory = getattr(props, 'total_memory', getattr(props, 'total_mem', None))
    print('VRAM total (GB):', total_memory / 1e9 if total_memory is not None else 'unknown')
    # Real synchronized tensor op
    x = torch.randn(4096, 4096, device='cuda')
    y = torch.randn(4096, 4096, device='cuda')
    z = torch.mm(x, y)
    torch.cuda.synchronize()
    print('matmul 4096x4096 OK, result norm:', z.norm().item())
    print('FP64 matmul test:')
    xd = torch.randn(2048, 2048, dtype=torch.float64, device='cuda')
    yd = torch.randn(2048, 2048, dtype=torch.float64, device='cuda')
    zd = torch.mm(xd, yd)
    torch.cuda.synchronize()
    print('  FP64 matmul OK, norm:', zd.norm().item())
" 2>&1 | tee -a "$OUTDIR/preflight.log"

log "Disk space"
df -h / /tmp /home 2>/dev/null | tee -a "$OUTDIR/preflight.log"

log "CPU / RAM"
nproc | tee -a "$OUTDIR/preflight.log"
free -h | tee -a "$OUTDIR/preflight.log"

log "Python / system versions"
python3 --version 2>&1 | tee -a "$OUTDIR/preflight.log"
uname -a | tee -a "$OUTDIR/preflight.log"

echo ""
echo "=== Preflight complete. Artifacts in: $OUTDIR ==="
echo "=== Share preflight.log + rocminfo.txt + gpu-smi.txt ==="
