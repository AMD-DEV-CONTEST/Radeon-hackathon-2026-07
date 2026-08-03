#!/bin/bash
# NVMe-oF TCP Initiator Connection from ML350e to T440
# Mounts T440's 48GB RAM as swap on ML350e
set -euo pipefail

echo "=== Connecting ML350e to T440's exported memory via TCP ==="

# Connect to T440's NVMe-oF TCP target
# T440 is at 10.0.0.61
nvme connect -t tcp -a 10.0.0.61 -s 4420 -n t440_memory_tcp

echo "Waiting for device to appear..."
sleep 2

# Find the connected NVMe device (should be ~48GB)
for dev in /dev/nvme1n1 /dev/nvme0n1; do
    if [ -b "$dev" ]; then
        SIZE=$(lsblk -b -d -o SIZE "$dev" 2>/dev/null | tail -1)
        if [ "$SIZE" = "52007458304" ] || [ "$SIZE" = "52013004800" ] || [ "$SIZE" -gt "40000000000" ]; then
            echo "Found remote NVMe device: $dev ($(($SIZE / 1024 / 1024 / 1024))GB)"
            # Turn it into active swap
            mkswap "$dev"
            swapon -p 32767 "$dev"
            echo "Configured $dev as high-priority swap (priority 32767)"
            break
        fi
    fi
done

# Verify swap
swapon --show | grep nvme && echo "Swap setup successful!" || echo "Swap not found - check connection"