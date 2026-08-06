#!/usr/bin/env bash
echo "=== Python binaries ==="
ls -la /usr/bin/python3* /usr/local/bin/python3* 2>/dev/null

echo ""
echo "=== conda/venv ==="
ls -la /opt/conda/bin/python* 2>/dev/null || echo "No conda at /opt/conda"
which conda 2>/dev/null || echo "No conda in PATH"

echo ""
echo "=== Find torch installations ==="
find / -name "torch" -type d -path "*/site-packages/torch" 2>/dev/null | head -10

echo ""
echo "=== Find vllm installations ==="
find / -name "vllm" -type d -path "*/site-packages/vllm" 2>/dev/null | head -10

echo ""
echo "=== pip lists ==="
pip3 list 2>/dev/null | grep -i -E "torch|vllm" || echo "Nothing in pip3"
python3 -m pip list 2>/dev/null | grep -i -E "torch|vllm" || echo "Nothing in python3 -m pip"
