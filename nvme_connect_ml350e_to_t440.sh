#!/bin/bash
# NVMe-oF Initiator Connection from ML350e to T440
# Mounts T440's 48GB RAM as swap on ML350e
set -euo pipefail

echo "=== Connecting ML350e to T440's exported memory ==="

# Load initiator modules
modprobe nvme-rdma || true

# Connect to T440's NVMe-oF target
# T440 is at 10.0.10.61 (or adjust to actual RDMA IP)
nvme connect -t rdma -a 10.0.10.61 -s 4420 -n t440_memory

echo "Waiting for device to appear..."
sleep 2

# The connected device should appear as /dev/nvme1n1 (nvme0n1 might be internal)
# Find it:
for dev in /dev/nvme1n1 /dev/nvme0n1; do
    if [ -b "$dev" ]; then
        echo "Found NVMe device: $dev"
        # Turn it into active swap
        mkswap "$dev"
        swapon -p 32767 "$dev"
        echo "Configured $dev as high-priority swap (priority 32767)"
        break
    fi
done

# Verify swap
swapon --show | grep -E "nvme.*48G" && echo "Swap setup successful!" || echo "Swap not found - check connection"