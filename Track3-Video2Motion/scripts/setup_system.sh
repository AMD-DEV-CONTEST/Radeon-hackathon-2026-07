#!/usr/bin/env bash
# APT packages. Run once, needs sudo.
source "$(dirname "$0")/common.sh"

step "System packages"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3.12-dev python3-pip \
    git wget curl ca-certificates build-essential cmake ninja-build \
    ffmpeg xvfb libegl1 libgl1 libglfw3 libosmesa6 \
    libeigen3-dev libyaml-dev
info "xvfb is required by GMR's retargeting script; ffmpeg by every render step."

step "TLS interception check"
# Some hosting environments (the AMD cloud image among them) route GitHub,
# Docker and HuggingFace through a caching proxy that re-signs TLS with its own
# CA. git then fails every clone with
#   server certificate verification failed. CAfile: none
# even though ca-certificates is installed and current. Trust the proxy's root
# if one is present.
if ! curl -sS -o /dev/null --max-time 20 https://github.com 2>/dev/null; then
  info "HTTPS to github.com fails — checking for an intercepting proxy"
  echo | timeout 15 openssl s_client -showcerts -connect github.com:443 \
        -servername github.com 2>/dev/null | awk '/BEGIN CERT/,/END CERT/' > /tmp/v2m_chain.pem
  if [ -s /tmp/v2m_chain.pem ]; then
    SUBJ=$(openssl x509 -in /tmp/v2m_chain.pem -noout -subject 2>/dev/null || true)
    info "presented certificate: $SUBJ"
    sudo mkdir -p /usr/local/share/ca-certificates
    sudo cp /tmp/v2m_chain.pem /usr/local/share/ca-certificates/v2m-proxy-root.crt
    sudo update-ca-certificates >/dev/null 2>&1
    if curl -sS -o /dev/null --max-time 20 https://github.com 2>/dev/null; then
      info "proxy CA trusted; HTTPS works now"
    else
      info "still failing — clone the dependencies manually, or set V2M_THIRD_PARTY"
    fi
  fi
else
  info "HTTPS to github.com is fine"
fi
