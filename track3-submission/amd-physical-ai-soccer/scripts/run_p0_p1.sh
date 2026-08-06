#!/bin/bash
# Combined experiment runner: P0 (60s kick) + P1 (rule vs rule 6-worker)
set +e
cd /workspace/radeon-repo
PYTHON=/opt/venv/bin/python
ONNX=models/chase_v8_policy.onnx
LOGDIR=/persistent/track3/match_logs

pkill -f match_worker 2>/dev/null; pkill -f match_coordinator 2>/dev/null; sleep 2

# ============================================================
# P0: 3 matches, 60s duration, RL+kick vs Rule, 3v3
# ============================================================
echo "[ $(date -u) ] === P0: 60s RL+kick vs Rule (3 matches) ==="
for i in 1 2 3; do
    PORT=$((9920 + i))
    echo "[ $(date -u) ] P0 Match $i/3 (port=$PORT, 60s)"
    
    $PYTHON match_coordinator.py --port $PORT --n-teams 2 --duration 60.0 --log-dir $LOGDIR > /tmp/p0_coord_${i}.log 2>&1 &
    COORD_PID=$!
    sleep 5
    
    $PYTHON match_worker_v3.py --role A_attacker --has-ball --port $PORT --onnx $ONNX --init-pos -1.0 0.0 0.7 > /tmp/p0_a1_${i}.log 2>&1 &
    $PYTHON match_worker_v3.py --role A_defender --port $PORT --onnx $ONNX --init-pos -3.5 1.5 0.7 > /tmp/p0_a2_${i}.log 2>&1 &
    $PYTHON match_worker_v3.py --role A_keeper --port $PORT --onnx $ONNX --init-pos -6.5 0.0 0.7 > /tmp/p0_a3_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_attacker --port $PORT --init-pos 1.0 0.0 0.7 > /tmp/p0_b1_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_defender --port $PORT --init-pos 3.5 -1.5 0.7 > /tmp/p0_b2_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_keeper --port $PORT --init-pos 6.5 0.0 0.7 > /tmp/p0_b3_${i}.log 2>&1 &
    
    wait $COORD_PID 2>/dev/null
    sleep 2
    kill $(jobs -p) 2>/dev/null
    echo "[ $(date -u) ] P0 Match $i done"
done

echo "[ $(date -u) ] === P0 complete ==="

# ============================================================
# P1: 5 matches, 25s, rule vs rule, 6-worker architecture
# ============================================================
echo "[ $(date -u) ] === P1: rule vs rule 6-worker (5 matches) ==="
for i in 1 2 3 4 5; do
    PORT=$((9930 + i))
    echo "[ $(date -u) ] P1 Match $i/5 (port=$PORT)"
    
    $PYTHON match_coordinator.py --port $PORT --n-teams 2 --duration 25.0 --log-dir $LOGDIR > /tmp/p1_coord_${i}.log 2>&1 &
    COORD_PID=$!
    sleep 5
    
    # Both teams rule-based (no --onnx)
    $PYTHON match_worker.py --role A_attacker --has-ball --port $PORT --init-pos -1.0 0.0 0.7 > /tmp/p1_a1_${i}.log 2>&1 &
    $PYTHON match_worker.py --role A_defender --port $PORT --init-pos -3.5 1.5 0.7 > /tmp/p1_a2_${i}.log 2>&1 &
    $PYTHON match_worker.py --role A_keeper --port $PORT --init-pos -6.5 0.0 0.7 > /tmp/p1_a3_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_attacker --port $PORT --init-pos 1.0 0.0 0.7 > /tmp/p1_b1_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_defender --port $PORT --init-pos 3.5 -1.5 0.7 > /tmp/p1_b2_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_keeper --port $PORT --init-pos 6.5 0.0 0.7 > /tmp/p1_b3_${i}.log 2>&1 &
    
    wait $COORD_PID 2>/dev/null
    sleep 2
    kill $(jobs -p) 2>/dev/null
    echo "[ $(date -u) ] P1 Match $i done"
done

echo "[ $(date -u) ] === P1 complete ==="
echo "DONE" > /tmp/p0p1_done.flag
