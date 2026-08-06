#!/bin/bash
# scripts/run_optimization.sh — inference optimization full-flow orchestration script
#
# 4-phase optimization experiments:
#   Phase 1: OSL dynamic limit (no vLLM restart needed)
#   Phase 2: INT4 GPTQ quantization (vLLM restart needed)
#   Phase 3: batching parameter optimization (vLLM restart needed)
#   Phase 4: end-to-end validation + quality evaluation
#
# Usage:
#   bash scripts/run_optimization.sh           # all 4 phases
#   bash scripts/run_optimization.sh phase1    # Phase 1 only
#   bash scripts/run_optimization.sh phase2    # Phase 2 only
#   bash scripts/run_optimization.sh phase3    # Phase 3 only
#   bash scripts/run_optimization.sh phase4    # Phase 4 only
#   bash scripts/run_optimization.sh summary   # generate summary only
#
# Prerequisites:
#   - vLLM service running (Phase 1 requires FP16 mode)
#   - Source model ./models/Qwen3-8B downloaded (Phase 2 requires this)
#   - venv activated

set -e
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BENCH_DIR="$PROJECT_ROOT/docs/benchmarks"
BASELINE_FILE="$BENCH_DIR/benchmarks/vllm_profile.json"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BENCH_DIR"

# ── color output ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()   { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()  { echo -e "${RED}[ERROR]${NC} $1"; }
log_phase()  { echo -e "\n${BLUE}════════════════════════════════════════════════════${NC}"; echo -e "${BLUE}  $1${NC}"; echo -e "${BLUE}════════════════════════════════════════════════════${NC}\n"; }

# ── check the vLLM service ──
check_vllm() {
    local label="$1"
    if curl -s --max-time 5 http://localhost:8000/v1/models | python -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null; then
        log_info "vLLM service is available ($label)"
        return 0
    else
        log_error "vLLM service is unavailable ($label)"
        log_error "Please start it first: bash scripts/start_vllm.sh"
        return 1
    fi
}

# ── check file existence ──
check_file() {
    if [ ! -f "$1" ]; then
        log_error "File does not exist: $1"
        return 1
    fi
    return 0
}

# ═══════════════════════════════════════════════════════════════
# Phase 1: OSL dynamic limit
# ═══════════════════════════════════════════════════════════════
run_phase1() {
    log_phase "Phase 1: OSL dynamic limit experiment"

    check_vllm "Phase 1" || return 1
    check_file "$BASELINE_FILE" || { log_warn "Baseline file does not exist; will only save the optimization results"; }

    local OSL_LIST="256 128 64"
    local CONC="1,4,8"

    for osl in $OSL_LIST; do
        local output="$BENCH_DIR/opt_osl_${osl}.json"
        log_info "Running OSL=$osl (concurrency: $CONC)..."

        python "$SCRIPT_DIR/vllm_profile.py" \
            --model Qwen3-8B \
            --concurrency "$CONC" \
            --isl 512 --osl "$osl" \
            --timeout 180 \
            --output "$output"

        log_info "OSL=$osl complete → $output"
    done

    log_info "Phase 1 complete: 3 groups of OSL comparison data"
    echo ""
    echo "  Comparison table:"
    echo "  OSL  | output_tps (conc=4) | p50 latency"
    echo "  -----|---------------------|--------"
    for osl in $OSL_LIST; do
        local f="$BENCH_DIR/opt_osl_${osl}.json"
        if [ -f "$f" ]; then
            python -c "
import json
with open('$f') as fp:
    d = json.load(fp)
for r in d['benchmark_results']:
    if r['concurrency'] == 4:
        print(f'  {\"$osl\":>4} | {r[\"output_tps\"]:>19.1f} | {r[\"lat_p50_s\"]:.3f}s')
" 2>/dev/null || echo "  $osl | (parse failed) |"
        fi
    done
}

# ═══════════════════════════════════════════════════════════════
# Phase 2: INT4 GPTQ quantization
# ═══════════════════════════════════════════════════════════════
run_phase2() {
    log_phase "Phase 2: INT4 GPTQ quantization experiment"

    local MODEL_FP16="$PROJECT_ROOT/models/Qwen3-8B"
    local MODEL_INT4="$PROJECT_ROOT/models/Qwen3-8B-GPTQ-Int4"

    # Step 1: check the source model
    if [ ! -d "$MODEL_FP16" ]; then
        log_error "Source model does not exist: $MODEL_FP16"
        log_error "Please first run: bash scripts/download_models.sh"
        return 1
    fi

    # Step 2: quantize (if the INT4 model does not exist)
    if [ -d "$MODEL_INT4" ] && [ -f "$MODEL_INT4/config.json" ]; then
        log_info "INT4 model already exists, skipping quantization: $MODEL_INT4"
    else
        log_info "Starting GPTQ INT4 quantization (estimated 10-30 minutes)..."
        python "$SCRIPT_DIR/quantize_gptq.py" \
            --source "$MODEL_FP16" \
            --target "$MODEL_INT4" \
            --bits 4 --group-size 128 --calib-samples 128

        if [ $? -ne 0 ]; then
            log_error "Quantization failed"
            return 1
        fi
        log_info "Quantization complete: $MODEL_INT4"
    fi

    # Step 3: prompt the user to restart vLLM
    log_warn "══════════════════════════════════════════════════════"
    log_warn "  You need to manually restart vLLM in INT4 mode"
    log_warn "  Run in another terminal:"
    log_warn "    bash scripts/start_vllm.sh --int4"
    log_warn "  Then press Enter to continue..."
    log_warn "══════════════════════════════════════════════════════"
    read -p "Press Enter to continue (vLLM INT4 started)..."

    # Step 4: verify vLLM
    check_vllm "INT4" || return 1

    # Step 5: run the INT4 performance benchmark (OSL=512)
    local output_512="$BENCH_DIR/opt_int4_512.json"
    log_info "Running the INT4 OSL=512 performance benchmark..."
    python "$SCRIPT_DIR/vllm_profile.py" \
        --model Qwen3-8B \
        --concurrency 1,4,8,16 \
        --isl 512 --osl 512 \
        --timeout 180 \
        --output "$output_512"
    log_info "INT4 OSL=512 complete → $output_512"

    # Step 6: run the INT4 + OSL=256 combination
    local output_256="$BENCH_DIR/opt_int4_256.json"
    log_info "Running the INT4 OSL=256 performance benchmark..."
    python "$SCRIPT_DIR/vllm_profile.py" \
        --model Qwen3-8B \
        --concurrency 1,4,8,16 \
        --isl 512 --osl 256 \
        --timeout 180 \
        --output "$output_256"
    log_info "INT4 OSL=256 complete → $output_256"

    # print the comparison
    echo ""
    echo "  INT4 vs FP16 comparison (conc=4, OSL=512):"
    echo "  Config | output_tps | p50 latency | speedup"
    echo "  ------|-----------|---------|-------"
    python -c "
import json, os
base_path = '$BASELINE_FILE'
int4_path = '$BENCH_DIR/opt_int4_512.json'
for label, path in [('FP16', base_path), ('INT4', int4_path)]:
    if os.path.isfile(path):
        with open(path) as f:
            d = json.load(f)
        for r in d['benchmark_results']:
            if r['concurrency'] == 4:
                print(f'  {label:>5} | {r[\"output_tps\"]:>9.1f} | {r[\"lat_p50_s\"]:.3f}s  |')
                break
# compute the speedup
if os.path.isfile(base_path) and os.path.isfile(int4_path):
    with open(base_path) as f: b = json.load(f)
    with open(int4_path) as f: i = json.load(f)
    for r_b, r_i in zip(b['benchmark_results'], i['benchmark_results']):
        if r_b['concurrency'] == 4:
            speedup = r_i['output_tps'] / r_b['output_tps'] if r_b['output_tps'] > 0 else 0
            print(f'  Speedup: {speedup:.2f}x')
            break
" 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════
# Phase 3: batching parameter optimization
# ═══════════════════════════════════════════════════════════════
run_phase3() {
    log_phase "Phase 3: batching parameter optimization experiment"

    check_vllm "Phase 3 (INT4)" || return 1

    # verify that the current mode is INT4
    local model_info
    model_info=$(curl -s http://localhost:8000/v1/models 2>/dev/null)
    if echo "$model_info" | grep -q "Qwen3-8B"; then
        log_info "vLLM service is available"
    else
        log_error "vLLM service is unavailable or the model name does not match"
        return 1
    fi

    # check whether the INT4 baseline exists
    local int4_baseline="$BENCH_DIR/opt_int4_512.json"
    if [ ! -f "$int4_baseline" ]; then
        log_warn "INT4 baseline does not exist ($int4_baseline)"
        log_warn "It is recommended to run Phase 2 first"
    fi

    log_warn "══════════════════════════════════════════════════════"
    log_warn "  Phase 3 requires modifying the vLLM startup parameters (max_num_seqs=16)"
    log_warn "  Run the following command in another terminal to start INT4 + batch=16:"
    log_warn ""
    log_warn "    python -m vllm.entrypoints.openai.api_server \\"
    log_warn "        --model ./models/Qwen3-8B-GPTQ-Int4 \\"
    log_warn "        --quantization gptq \\"
    log_warn "        --served-model-name Qwen3-8B \\"
    log_warn "        --device 0 --dtype bfloat16 \\"
    log_warn "        --max-model-len 4096 \\"
    log_warn "        --max-num-seqs 16 \\"
    log_warn "        --gpu-memory-utilization 0.90 \\"
    log_warn "        --enable-prefix-caching \\"
    log_warn "        --enable-chunked-prefill \\"
    log_warn "        --enforce-eager \\"
    log_warn "        --chat-template ./models/qwen3_nonthinking.jinja \\"
    log_warn "        --port 8000"
    log_warn ""
    log_warn "  Then press Enter to continue..."
    log_warn "══════════════════════════════════════════════════════"
    read -p "Press Enter to continue (vLLM INT4+batch16 started)..."

    check_vllm "INT4+batch16" || return 1

    local output="$BENCH_DIR/opt_int4_batch16.json"
    log_info "Running the INT4 + batch=16 performance benchmark..."
    python "$SCRIPT_DIR/vllm_profile.py" \
        --model Qwen3-8B \
        --concurrency 1,4,8,16 \
        --isl 512 --osl 512 \
        --timeout 180 \
        --output "$output"
    log_info "INT4 + batch=16 complete → $output"

    # print the comparison
    echo ""
    echo "  batch=4 vs batch=16 comparison (INT4, conc=4, OSL=512):"
    python -c "
import json, os
paths = {
    'batch=4': '$int4_baseline',
    'batch=16': '$output',
}
results = {}
for label, path in paths.items():
    if os.path.isfile(path):
        with open(path) as f:
            d = json.load(f)
        for r in d['benchmark_results']:
            if r['concurrency'] == 4:
                results[label] = r
                break
if len(results) == 2:
    b4 = results['batch=4']
    b16 = results['batch=16']
    speedup = b16['output_tps'] / b4['output_tps'] if b4['output_tps'] > 0 else 0
    print(f'  batch=4:  TPS={b4[\"output_tps\"]:.1f}, P50={b4[\"lat_p50_s\"]:.3f}s')
    print(f'  batch=16: TPS={b16[\"output_tps\"]:.1f}, P50={b16[\"lat_p50_s\"]:.3f}s')
    print(f'  Speedup: {speedup:.2f}x')
" 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════
# Phase 4: end-to-end validation + quality evaluation
# ═══════════════════════════════════════════════════════════════
run_phase4() {
    log_phase "Phase 4: end-to-end validation + quality evaluation"

    check_vllm "Phase 4" || return 1

    # Step 1: E2E load test — comparison mode
    local e2e_comp="$BENCH_DIR/opt_e2e_comparison_${TIMESTAMP}.json"
    log_info "Running the E2E load test (comparison mode)..."
    python "$SCRIPT_DIR/load_test.py" \
        --question-mode comparison \
        --requests 10 --concurrency 2 --timeout 120 \
        --output "$e2e_comp"
    log_info "E2E comparison complete → $e2e_comp"

    # Step 2: E2E load test — simple mode
    local e2e_simple="$BENCH_DIR/opt_e2e_simple_${TIMESTAMP}.json"
    log_info "Running the E2E load test (simple mode)..."
    python "$SCRIPT_DIR/load_test.py" \
        --question-mode simple \
        --requests 10 --concurrency 2 --timeout 60 \
        --output "$e2e_simple"
    log_info "E2E simple complete → $e2e_simple"

    # Step 3: quality evaluation (if evaluate.py exists)
    if [ -f "$SCRIPT_DIR/evaluate.py" ]; then
        local quality_report="$BENCH_DIR/opt_quality_report.json"
        log_info "Running the quality evaluation..."
        python "$SCRIPT_DIR/evaluate.py" \
            --output "$quality_report" 2>/dev/null || \
            log_warn "Quality evaluation script failed (non-blocking)"
    else
        log_warn "evaluate.py does not exist, skipping the quality evaluation"
    fi

    log_info "Phase 4 complete"
}

# ═══════════════════════════════════════════════════════════════
# Summary: generate the comparison summary
# ═══════════════════════════════════════════════════════════════
run_summary() {
    log_phase "Generating the optimization comparison summary"

    python "$SCRIPT_DIR/optimize_summary.py" \
        --bench-dir "$BENCH_DIR" \
        --output "$BENCH_DIR/opt_summary.json"
}

# ═══════════════════════════════════════════════════════════════
# main entry
# ═══════════════════════════════════════════════════════════════
main() {
    local target="${1:-all}"

    cd "$PROJECT_ROOT"

    echo ""
    echo "================================================================"
    echo "  Inference optimization execution script"
    echo "  Project: insurance-rag-agent"
    echo "  Time: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  Target: $target"
    echo "================================================================"
    echo ""

    case "$target" in
        phase1|p1)
            run_phase1
            ;;
        phase2|p2)
            run_phase2
            ;;
        phase3|p3)
            run_phase3
            ;;
        phase4|p4)
            run_phase4
            ;;
        summary)
            run_summary
            ;;
        all)
            run_phase1
            run_phase2
            run_phase3
            run_phase4
            run_summary
            ;;
        *)
            echo "Usage: bash $0 [phase1|phase2|phase3|phase4|summary|all]"
            echo ""
            echo "  phase1  — OSL dynamic limit experiment (no vLLM restart needed)"
            echo "  phase2  — INT4 GPTQ quantization experiment (vLLM restart needed)"
            echo "  phase3  — batching parameter optimization (vLLM restart needed)"
            echo "  phase4  — end-to-end validation + quality evaluation"
            echo "  summary — generate the comparison summary report"
            echo "  all     — all 4 phases + summary"
            exit 1
            ;;
    esac

    echo ""
    log_info "Optimization experiments complete!"
    log_info "View the summary: $BENCH_DIR/opt_summary.json"
    log_info "Execution plan: docs/OPTIMIZATION_EXECUTION_PLAN.md"
}

main "$@"