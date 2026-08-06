#!/bin/bash
# Wait for all training to finish, then render demo videos
cd /workspace/amd-physical-ai-soccer
export DISPLAY=:99

echo "[monitor] Waiting for training to complete..."

while true; do
    RUNNING=$(ps aux | grep 'train.py' | grep -v grep | wc -l)
    if [ "$RUNNING" -eq 0 ]; then
        echo "[monitor] All training processes finished!"
        break
    fi
    echo "[monitor] $RUNNING training processes still running..."
    echo "  balance: $(tail -1 /workspace/train_balance.log 2>/dev/null)"
    echo "  chase:   $(tail -1 /workspace/train_chase.log 2>/dev/null)"
    echo "  shoot:   $(tail -1 /workspace/train_shoot.log 2>/dev/null)"
    sleep 120
done

echo "[monitor] Training complete. Rendering demo videos..."

/opt/venv/bin/python3 /workspace/render_all.py 2>&1 | tee /workspace/render_all.log
