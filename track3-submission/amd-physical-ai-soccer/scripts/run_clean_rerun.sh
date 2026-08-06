#!/bin/bash
# Clean re-run with N_STEPS fix: 5 RL+kick(25s) + 3 RL+kick(60s) + 3 rule_vs_rule(25s)
set +e
cd /workspace/radeon-repo
PYTHON=/opt/venv/bin/python
ONNX=models/chase_v8_policy.onnx
LOGDIR=/persistent/track3/match_logs/clean_rerun
mkdir -p $LOGDIR

pkill -f match_worker 2>/dev/null; pkill -f match_coordinator 2>/dev/null; sleep 2

# ===== Group B_clean: 5 RL+kick vs Rule, 25s, varied seeds =====
echo "[ $(date -u) ] === B_clean: RL+kick vs Rule (5x25s) ==="
for i in 1 2 3 4 5; do
    PORT=$((9940 + i))
    SEED=$((100 + i))
    echo "[ $(date -u) ] B_clean $i/5 (port=$PORT, seed=$SEED)"
    $PYTHON match_coordinator.py --port $PORT --n-teams 2 --duration 25.0 --log-dir $LOGDIR > /tmp/clean_b_coord_${i}.log 2>&1 &
    COORD_PID=$!; sleep 5
    $PYTHON match_worker_v3.py --role A_attacker --has-ball --port $PORT --onnx $ONNX --init-pos -1.0 0.0 0.7 > /tmp/clean_b_a1_${i}.log 2>&1 &
    $PYTHON match_worker_v3.py --role A_defender --port $PORT --onnx $ONNX --init-pos -3.5 1.5 0.7 > /tmp/clean_b_a2_${i}.log 2>&1 &
    $PYTHON match_worker_v3.py --role A_keeper --port $PORT --onnx $ONNX --init-pos -6.5 0.0 0.7 > /tmp/clean_b_a3_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_attacker --port $PORT --init-pos 1.0 0.0 0.7 > /tmp/clean_b_b1_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_defender --port $PORT --init-pos 3.5 -1.5 0.7 > /tmp/clean_b_b2_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_keeper --port $PORT --init-pos 6.5 0.0 0.7 > /tmp/clean_b_b3_${i}.log 2>&1 &
    wait $COORD_PID 2>/dev/null; sleep 2; kill $(jobs -p) 2>/dev/null
    echo "[ $(date -u) ] B_clean $i done"
done

# ===== Group E_clean: 3 RL+kick vs Rule, 60s =====
echo "[ $(date -u) ] === E_clean: RL+kick vs Rule (3x60s) ==="
for i in 1 2 3; do
    PORT=$((9950 + i))
    SEED=$((200 + i))
    echo "[ $(date -u) ] E_clean $i/3 (port=$PORT, seed=$SEED, 60s)"
    $PYTHON match_coordinator.py --port $PORT --n-teams 2 --duration 60.0 --log-dir $LOGDIR > /tmp/clean_e_coord_${i}.log 2>&1 &
    COORD_PID=$!; sleep 5
    $PYTHON match_worker_v3.py --role A_attacker --has-ball --port $PORT --onnx $ONNX --init-pos -1.0 0.0 0.7 > /tmp/clean_e_a1_${i}.log 2>&1 &
    $PYTHON match_worker_v3.py --role A_defender --port $PORT --onnx $ONNX --init-pos -3.5 1.5 0.7 > /tmp/clean_e_a2_${i}.log 2>&1 &
    $PYTHON match_worker_v3.py --role A_keeper --port $PORT --onnx $ONNX --init-pos -6.5 0.0 0.7 > /tmp/clean_e_a3_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_attacker --port $PORT --init-pos 1.0 0.0 0.7 > /tmp/clean_e_b1_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_defender --port $PORT --init-pos 3.5 -1.5 0.7 > /tmp/clean_e_b2_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_keeper --port $PORT --init-pos 6.5 0.0 0.7 > /tmp/clean_e_b3_${i}.log 2>&1 &
    wait $COORD_PID 2>/dev/null; sleep 2; kill $(jobs -p) 2>/dev/null
    echo "[ $(date -u) ] E_clean $i done"
done

# ===== Group A_clean: 3 rule vs rule, 25s =====
echo "[ $(date -u) ] === A_clean: rule vs rule (3x25s) ==="
for i in 1 2 3; do
    PORT=$((9960 + i))
    SEED=$((300 + i))
    echo "[ $(date -u) ] A_clean $i/3 (port=$PORT, seed=$SEED)"
    $PYTHON match_coordinator.py --port $PORT --n-teams 2 --duration 25.0 --log-dir $LOGDIR > /tmp/clean_a_coord_${i}.log 2>&1 &
    COORD_PID=$!; sleep 5
    $PYTHON match_worker.py --role A_attacker --has-ball --port $PORT --init-pos -1.0 0.0 0.7 > /tmp/clean_a_a1_${i}.log 2>&1 &
    $PYTHON match_worker.py --role A_defender --port $PORT --init-pos -3.5 1.5 0.7 > /tmp/clean_a_a2_${i}.log 2>&1 &
    $PYTHON match_worker.py --role A_keeper --port $PORT --init-pos -6.5 0.0 0.7 > /tmp/clean_a_a3_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_attacker --port $PORT --init-pos 1.0 0.0 0.7 > /tmp/clean_a_b1_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_defender --port $PORT --init-pos 3.5 -1.5 0.7 > /tmp/clean_a_b2_${i}.log 2>&1 &
    $PYTHON match_worker.py --role B_keeper --port $PORT --init-pos 6.5 0.0 0.7 > /tmp/clean_a_b3_${i}.log 2>&1 &
    wait $COORD_PID 2>/dev/null; sleep 2; kill $(jobs -p) 2>/dev/null
    echo "[ $(date -u) ] A_clean $i done"
done

echo "[ $(date -u) ] === ALL CLEAN MATCHES DONE ==="
echo "DONE" > /tmp/clean_done.flag
