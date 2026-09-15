#!/usr/bin/env bash
# setup_ollama.sh — install Ollama and pull the models used by this project.
#
# Run from the project root (or anywhere). It installs Ollama system-wide via
# the official installer, then pulls:
#   * minicpm-v4.5:8b  — vision-language model used for frame description
#   * gpt-oss:20b      — text model used by the agentic retrieval chat
#
# After this script completes, start the Ollama daemon with:
#     ollama serve
set -euo pipefail

echo "==> Installing Ollama (requires curl, sudo for system install)"
if command -v ollama >/dev/null 2>&1; then
  echo "    ollama already installed: $(ollama --version)"
else
  curl -fsSL https://ollama.com/install.sh | sh
fi

echo "==> Pulling vision model: minicpm-v4.5:8b"
ollama pull minicpm-v4.5:8b

echo "==> Pulling agent model: gpt-oss:20b"
ollama pull gpt-oss:20b

echo
echo "Models ready. Start the server with:"
echo "    ollama serve"
echo ""
echo "Then verify with:"
echo "    ollama list"
