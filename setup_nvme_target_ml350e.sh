#!/bin/bash
# NVMe-oF RDMA Cross-Link Setup Script for ML350e (Target 2)
# Exports 32GB RAM to T440 via RDMA
set -euo pipefail

echo "=== Phase 1: Kernel modules (ML350e) ==="
modprobe nvmet nvmet-rdma nvme-rdma || true

echo "=== Phase 2: Setting up Target 2 (ML350e exports to T440) ==="

# 1. Create the RAM block (32GB)
mkdir -p /mnt/ml350e_share
mount -t tmpfs -o size=32G tmpfs /mnt/ml350e_share
truncate -s 32G /mnt/ml350e_share/ram_block.img
echo "Created 32G RAM block at /mnt/ml350e_share/ram_block.img"

# 2. Expose via NVMe-oF Target ConfigFS
mkdir -p /sys/kernel/config/nvmet/subsystems/ml350e_memory
echo 1 > /sys/kernel/config/nvmet/subsystems/ml350e_memory/attr_allow_any_host
echo "Created ml350e_memory subsystem with allow_any_host=1"

# 3. Bind the block image
mkdir -p /sys/kernel/config/nvmet/subsystems/ml350e_memory/namespaces/1
echo "/mnt/ml350e_share/ram_block.img" > /sys/kernel/config/nvmet/subsystems/ml350e_memory/namespaces/1/device_path
echo 1 > /sys/kernel/config/nvmet/subsystems/ml350e_memory/namespaces/1/enable
echo "Attached ram_block.img to namespace 1 and enabled"

# 4. Link to RDMA port
# This server should have IP 10.0.10.201 for the 25Gb RDMA network
# If using 10.0.0.201 instead, adjust accordingly
mkdir -p /sys/kernel/config/nvmet/ports/1
echo "rdma" > /sys/kernel/config/nvmet/ports/1/addr_trtype
echo "ipv4" > /sys/kernel/config/nvmet/ports/1/addr_adrfam
echo "10.0.10.201" > /sys/kernel/config/nvmet/ports/1/addr_traddr   # Adjust if needed
echo "4420" > /sys/kernel/config/nvmet/ports/1/addr_trsvcid
echo "Configured RDMA port 1 on 10.0.10.201:4420"

ln -sf /sys/kernel/config/nvmet/subsystems/ml350e_memory /sys/kernel/config/nvmet/ports/1/subsystems/ml350e_memory
echo "Linked ml350e_memory subsystem to port 1"

echo ""
echo "=== ML350e Target Setup Complete ==="
echo "ML350e is exporting 32GB RAM at NQN: ml350e_memory on 10.0.10.201:4420"
echo "T440 should connect with: nvme connect -t rdma -a 10.0.10.201 -s 4420 -n ml350e_memory"