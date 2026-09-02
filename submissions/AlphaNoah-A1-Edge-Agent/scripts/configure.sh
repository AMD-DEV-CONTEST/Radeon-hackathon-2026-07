#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/config/alphanoah.env"
choice=""
if [[ "${1:-}" == "--provider" ]]; then choice="${2:-}"; fi
echo "AlphaNoah Edge Runtime Setup"
if [[ -z "$choice" ]]; then
  cat <<TXT

Choose inference provider:

[1] Ollama
    Local inference on this device
[2] vLLM / OpenAI-Compatible Local Endpoint
    Inference on local or LAN GPU server
[3] API Key / Remote OpenAI-Compatible Endpoint
    Inference through external/private API
[4] Fake Demo Provider
    Deterministic demonstration without a model
TXT
  read -r -p "Selection [1-4]: " choice
fi
provider="" model="" base_url="" api_key="" scope="" egress="None"
case "$choice" in
  1|ollama)
    provider=ollama; base_url="http://127.0.0.1:11434"
    command -v ollama >/dev/null && {
      version="$(ollama version 2>/dev/null || ollama --version 2>/dev/null || true)"
      echo "Detected ${version:-Ollama}"
      ollama list 2>/dev/null || true
    }
    if [[ -t 0 ]]; then read -r -p "Model [qwen3.5:9b]: " model; fi
    model="${model:-qwen3.5:9b}"; scope="This device"
    ;;
  2|vllm)
    provider=openai_compatible
    if [[ -t 0 ]]; then read -r -p "Endpoint [http://127.0.0.1:8000/v1]: " base_url; read -r -p "Model: " model; read -r -s -p "API Key (optional): " api_key; echo; fi
    base_url="${base_url:-${ALPHANOAH_SETUP_BASE_URL:-http://127.0.0.1:8000/v1}}"
    model="${model:-${ALPHANOAH_SETUP_MODEL:-model}}"; api_key="${api_key:-${ALPHANOAH_SETUP_API_KEY:-}}"
    scope="$(python3 - "$base_url" <<\PY
import ipaddress,sys
from urllib.parse import urlsplit
h=(urlsplit(sys.argv[1]).hostname or "").lower()
try: a=ipaddress.ip_address(h)
except ValueError: print("This device" if h=="localhost" else "External network")
else: print("This device" if a.is_loopback else "Enterprise LAN" if a.is_private else "External network")
PY
)"; [[ "$scope" == "Enterprise LAN" ]] && egress="LAN only" || [[ "$scope" == "External network" ]] && egress="External"
    ;;
  3|remote)
    provider=openai_compatible
    if [[ -t 0 ]]; then
      read -r -p "Base URL: " base_url; read -r -p "Model: " model; read -r -s -p "API Key: " api_key; echo
      cat <<WARN
WARNING
This provider may transmit incident, knowledge and analysis context outside
this device or enterprise network.
WARN
      read -r -p "Continue? [y/N] " confirm; [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
    else
      [[ "${ALPHANOAH_REMOTE_CONSENT:-}" == "yes" ]] || { echo "Remote provider requires ALPHANOAH_REMOTE_CONSENT=yes."; exit 2; }
    fi
    base_url="${base_url:-${ALPHANOAH_SETUP_BASE_URL:-}}"; model="${model:-${ALPHANOAH_SETUP_MODEL:-}}"; api_key="${api_key:-${ALPHANOAH_SETUP_API_KEY:-}}"
    [[ -n "$base_url" && -n "$model" && -n "$api_key" ]] || { echo "Base URL, model and API key are required."; exit 2; }
    scope="External network"; egress="External"
    ;;
  4|fake) provider=fake; scope="Simulation" ;;
  *) echo "Invalid provider selection."; exit 2 ;;
esac
offline="${ALPHANOAH_OFFLINE_ONLY:-false}"
if [[ "$offline" == "true" && "$scope" == "External network" ]]; then echo "offline-only blocks public endpoints."; exit 2; fi
umask 077
{
  printf "ALPHANOAH_PROVIDER=%q\n" "$provider"
  printf "ALPHANOAH_MODEL=%q\n" "$model"
  printf "ALPHANOAH_BASE_URL=%q\n" "$base_url"
  printf "ALPHANOAH_API_KEY=%q\n" "$api_key"
  printf "ALPHANOAH_PORT=%q\n" "${ALPHANOAH_PORT:-8090}"
  printf "ALPHANOAH_OFFLINE_ONLY=%q\n" "$offline"
  printf "ALPHANOAH_INFERENCE_SCOPE=%q\n" "$scope"
  printf "ALPHANOAH_DATA_EGRESS=%q\n" "$egress"
} > "$OUT"
chmod 600 "$OUT"
echo "Configuration saved securely."
echo "Provider: $provider"
echo "Inference scope: $scope"
