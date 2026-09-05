#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "ERROR: run this recovery script as root from the Radeon Cloud terminal."
  exit 1
fi

if [[ ! -x /usr/sbin/sshd ]]; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server
fi

mkdir -p /run/sshd
/usr/sbin/sshd -t

if pgrep -x sshd >/dev/null 2>&1; then
  echo "sshd is already running."
else
  /usr/sbin/sshd
  echo "sshd started."
fi

echo "Verify from the Mac with: ssh -o BatchMode=yes amd-radeon true"
