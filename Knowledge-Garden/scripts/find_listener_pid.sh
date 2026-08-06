#!/bin/bash
# find_listener_pid.sh — resolve a listening TCP port to its owning PID using only /proc (no ss/lsof).
# Usage: bash scripts/find_listener_pid.sh <port>
set -u
PORT="${1:?port required}"
HEX="$(printf '%04X' "$PORT")"
# /proc/net/tcp: local_address is hex IP:hex port; field 10 is inode
for tcpf in /proc/net/tcp /proc/net/tcp6; do
  [ -r "$tcpf" ] || continue
  INODE="$(awk -v h="$HEX" '$2 ~ ":"h"$" {print $10; exit}' "$tcpf")"
  [ -n "$INODE" ] && break
done
[ -n "$INODE" ] || { echo "find_listener_pid: no listener for port $PORT" >&2; exit 1; }
# find process holding that inode
for p in /proc/[0-9]*; do
  [ -d "$p" ] || continue
  if ls -l "$p/fd" 2>/dev/null | grep -q "socket:\[$INODE\]"; then
    echo "${p#/proc/}"
    exit 0
  fi
done
# fallback: any fd symlink to the inode via /proc/*/fd
for p in /proc/[0-9]*/fd/*; do
  tgt="$(readlink "$p" 2>/dev/null || true)"
  case "$tgt" in
    "socket:[$INODE]") echo "${p#/proc/}"; echo "${p}" >/dev/null; pid="${p#/proc/}"; pid="${pid%%/*}"; echo "$pid"; exit 0;;
  esac
done
echo "find_listener_pid: inode $INODE not mapped to any PID" >&2
exit 1
