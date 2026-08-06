#!/bin/bash
# ============================================================
# Deploy files to cloud and run t1_walk.pt verification
#
# Usage on local Mac:
#   bash deploy_and_verify.sh
#
# Or run manually on cloud after copying files:
#   cd /workspace/amd-physical-ai-soccer
#   bash deploy_fixes.sh
# ============================================================
set -e

CLOUD_DIR="${1:-/workspace/amd-physical-ai-soccer}"

echo "============================================"
echo "  Deployment: v4 env + hierarchical training"
echo "============================================"
echo "  Cloud dir: $CLOUD_DIR"
echo ""

# ---- Step 1: Copy fixed files ----
echo "[1/5] Copying fixed files..."

# soccer_env_v4.py → envs/soccer_env.py (the module all scripts import)
if [ -f soccer_env_v4.py ]; then
    mkdir -p "$CLOUD_DIR/envs"
    cp soccer_env_v4.py "$CLOUD_DIR/envs/soccer_env.py"
    echo "  ✓ envs/soccer_env.py updated (v4 with obs_scales fix)"
fi

# soccer_env_hierarchical.py → envs/soccer_env_hierarchical.py
if [ -f soccer_env_hierarchical.py ]; then
    cp soccer_env_hierarchical.py "$CLOUD_DIR/envs/soccer_env_hierarchical.py"
    echo "  ✓ envs/soccer_env_hierarchical.py deployed"
fi

# reward.py → rewards/reward.py (includes chase_hl task)
if [ -f reward.py ]; then
    mkdir -p "$CLOUD_DIR/rewards"
    cp reward.py "$CLOUD_DIR/rewards/reward.py"
    echo "  ✓ rewards/reward.py updated (with chase_hl task)"
fi

# configs
if [ -f configs/soccer_agent.yaml ]; then
    mkdir -p "$CLOUD_DIR/configs"
    cp configs/soccer_agent.yaml "$CLOUD_DIR/configs/soccer_agent.yaml"
    echo "  ✓ configs/soccer_agent.yaml copied"
fi
if [ -f configs/hierarchical_agent.yaml ]; then
    cp configs/hierarchical_agent.yaml "$CLOUD_DIR/configs/hierarchical_agent.yaml"
    echo "  ✓ configs/hierarchical_agent.yaml deployed"
fi

# Training scripts
if [ -f train_hierarchical.py ]; then
    cp train_hierarchical.py "$CLOUD_DIR/train_hierarchical.py"
    echo "  ✓ train_hierarchical.py deployed"
fi

# verify_t1_walk.py
if [ -f verify_t1_walk.py ]; then
    cp verify_t1_walk.py "$CLOUD_DIR/verify_t1_walk.py"
    echo "  ✓ verify_t1_walk.py copied"
fi

# Create __init__.py if missing
touch "$CLOUD_DIR/envs/__init__.py" "$CLOUD_DIR/rewards/__init__.py" 2>/dev/null || true

echo ""

# ---- Step 2: Verify t1_walk.pt exists ----
echo "[2/5] Checking t1_walk.pt..."
T1_PATH="/workspace/booster/booster_deploy/tasks/locomotion/models/t1_walk.pt"
if [ -f "$T1_PATH" ]; then
    echo "  ✓ Found: $T1_PATH"
else
    echo "  ⚠ Not found at $T1_PATH, searching..."
    find /workspace -name "t1_walk.pt" 2>/dev/null | head -5
fi
echo ""

# ---- Step 3: Run walking verification ----
echo "[3/5] Running t1_walk.pt verification..."
echo ""
cd "$CLOUD_DIR"
python verify_t1_walk.py
RESULT=$?
echo ""

# ---- Step 4: Report verification ----
echo "[4/5] Verification result:"
if [ $RESULT -eq 0 ]; then
    echo "  ✅ PASS — t1_walk.pt walked 30s without falling"
else
    echo "  ❌ FAIL — t1_walk.pt fell within 30s"
    echo "  Try: python verify_t1_walk.py --no_norm"
fi
echo ""

# ---- Step 5: Print hierarchical training instructions ----
echo "[5/5] Hierarchical training instructions:"
echo "  cd $CLOUD_DIR"
echo ""
echo "  # Quick test (100 iterations, 256 envs):"
echo "  python train_hierarchical.py --num_envs 256 --max_iterations 100"
echo ""
echo "  # Full training (500 iterations):"
echo "  python train_hierarchical.py --max_iterations 500"
echo ""
echo "  Models saved to: runs/hierarchical_soccer_chase_hl/"
