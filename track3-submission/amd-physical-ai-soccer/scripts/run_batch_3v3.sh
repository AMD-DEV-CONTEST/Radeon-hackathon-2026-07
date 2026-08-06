#!/bin/bash
# Batch 3v3 match runner: runs N matches and collects stats
# Usage: bash run_batch_3v3.sh <n_matches> <mode> <onnx_path>
# Modes: rule_vs_rule | rl_vs_rule
set +e

N_MATCHES="${1:-5}"
MODE="${2:-rl_vs_rule}"
ONNX="${3:-models/chase_v8_policy.onnx}"
PORT_BASE=9900
LOGDIR=/persistent/track3/match_logs
PYTHON=/opt/venv/bin/python

cd /workspace/radeon-repo
mkdir -p $LOGDIR

echo "[ $(date -u) ] Starting batch: $N_MATCHES matches, mode=$MODE, onnx=$ONNX"

for ((i=1; i<=N_MATCHES; i++)); do
    PORT=$((PORT_BASE + i))
    SEED=$((42 + i))
    echo "[ $(date -u) ] Match $i/$N_MATCHES (port=$PORT, seed=$SEED)"
    
    pkill -f match_worker 2>/dev/null; pkill -f match_coordinator 2>/dev/null; sleep 2
    
    $PYTHON match_coordinator.py --port $PORT --n-teams 2 --duration 25.0 --log-dir $LOGDIR > /tmp/batch_coord_${i}.log 2>&1 &
    COORD_PID=$!
    sleep 5
    
    if [ "$MODE" == "rl_vs_rule" ]; then
        # Team A: RL (ONNX), Team B: Rule
        $PYTHON match_worker.py --role A_attacker --has-ball --port $PORT --onnx "$ONNX" --init-pos -1.0 0.0 0.7 > /tmp/batch_a1_${i}.log 2>&1 &
        $PYTHON match_worker.py --role A_defender --port $PORT --onnx "$ONNX" --init-pos -3.5 1.5 0.7 > /tmp/batch_a2_${i}.log 2>&1 &
        $PYTHON match_worker.py --role A_keeper --port $PORT --onnx "$ONNX" --init-pos -6.5 0.0 0.7 > /tmp/batch_a3_${i}.log 2>&1 &
        
        $PYTHON match_worker.py --role B_attacker --port $PORT --init-pos 1.0 0.0 0.7 > /tmp/batch_b1_${i}.log 2>&1 &
        $PYTHON match_worker.py --role B_defender --port $PORT --init-pos 3.5 -1.5 0.7 > /tmp/batch_b2_${i}.log 2>&1 &
        $PYTHON match_worker.py --role B_keeper --port $PORT --init-pos 6.5 0.0 0.7 > /tmp/batch_b3_${i}.log 2>&1 &
    elif [ "$MODE" == "rule_vs_rule" ]; then
        # Both teams: Rule
        $PYTHON match_worker.py --role A_attacker --has-ball --port $PORT --init-pos -1.0 0.0 0.7 > /tmp/batch_a1_${i}.log 2>&1 &
        $PYTHON match_worker.py --role A_defender --port $PORT --init-pos -3.5 1.5 0.7 > /tmp/batch_a2_${i}.log 2>&1 &
        $PYTHON match_worker.py --role A_keeper --port $PORT --init-pos -6.5 0.0 0.7 > /tmp/batch_a3_${i}.log 2>&1 &
        
        $PYTHON match_worker.py --role B_attacker --port $PORT --init-pos 1.0 0.0 0.7 > /tmp/batch_b1_${i}.log 2>&1 &
        $PYTHON match_worker.py --role B_defender --port $PORT --init-pos 3.5 -1.5 0.7 > /tmp/batch_b2_${i}.log 2>&1 &
        $PYTHON match_worker.py --role B_keeper --port $PORT --init-pos 6.5 0.0 0.7 > /tmp/batch_b3_${i}.log 2>&1 &
    fi
    
    wait $COORD_PID 2>/dev/null
    sleep 2
    kill $(jobs -p) 2>/dev/null
    echo "[ $(date -u) ] Match $i done"
done

echo "[ $(date -u) ] All $N_MATCHES matches complete"
echo "DONE" > /tmp/batch_done.flag
