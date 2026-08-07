#!/bin/bash
# NVMe-oF TCP Cross-Link Setup Script for ML350e (Target 2)
# Exports 32GB RAM to T440 via TCP
set -euo pipefail

echo "=== Phase 2 (TCP): Setting up Target 2 (ML350e exports to T440) ==="

# 1. Create the RAM block (32GB)
mkdir -p /mnt/ml350e_share
mount -t tmpfs -o size=32G tmpfs /mnt/ml350e_share
truncate -s 32G /mnt/ml350e_share/ram_block.img
echo "Created 32G RAM block at /mnt/ml350e_share/ram_block.img"

# 2. Expose via NVMe-oF Target ConfigFS
mkdir -p /sys/kernel/config/nvmet/subsystems/ml350e_memory_tcp
echo 1 > /sys/kernel/config/nvmet/subsystems/ml350e_memory_tcp/attr_allow_any_host
echo "Created ml350e_memory_tcp subsystem with allow_any_host=1"

# 3. Bind the block image
mkdir -p /sys/kernel/config/nvmet/subsystems/ml350e_memory_tcp/namespaces/1
echo "/mnt/ml350e_share/ram_block.img" > /sys/kernel/config/nvmet/subsystems/ml350e_memory_tcp/namespaces/1/device_path
echo 1 > /sys/kernel/config/nvmet/subsystems/ml350e_memory_tcp/namespaces/1/enable
echo "Attached ram_block.img to namespace 1 and enabled"

# 4. Link to TCP port (use 10.0.0.201 IP)
mkdir -p /sys/kernel/config/nvmet/ports/2
echo "tcp" > /sys/kernel/config/nvmet/ports/2/addr_trtype
echo "ipv4" > /sys/kernel/config/nvmet/ports/2/addr_adrfam
echo "10.0.0.201" > /sys/kernel/config/nvmet/ports/2/addr_traddr
echo "4420" > /sys/kernel/config/nvmet/ports/2/addr_trsvcid
echo "Configured TCP port 2 on 10.0.0.201:4420"

ln -sf /sys/kernel/config/nvmet/subsystems/ml350e_memory_tcp /sys/kernel/config/nvmet/ports/2/subsystems/ml350e_memory_tcp
echo "Linked ml350e_memory_tcp subsystem to port 2"

echo ""
echo "=== ML350e TCP Target Setup Complete ==="
echo "ML350e is exporting 32GB RAM at NQN: ml350e_memory_tcp on 10.0.0.201:4420"