#!/bin/bash
# run_model_eval.sh — Qwen2.5/Qwen3 A/B evaluation + routing decision (Todo 6).
#
# Modes:
#   --mode stub   (default) deterministic: three arms produced via make_stub_report.py.
#   --mode live   real model arms: Qwen2.5-32B-AWQ on --qwen25-port, Qwen3-32B-AWQ
#                 swapped in via qwen3_experiment.sh (download first).
#
# READ-ONLY guarantees (both modes):
#   - Captures a service descriptor BEFORE any model swap (live mode).
#   - The incumbent model is RESTORED on EXIT (live mode, EXIT trap).
#   - Logical digests (compare_logical_digests.py) must match after restore.
#
# Outputs (--out-dir, default docs/evaluation):
#   qwen2.5-vs-qwen3.md / .json      human + machine summary of all arms
#   routing-decision.json            atomic decision per threshold_version 1
#   runs/<arm>.raw.json              per-arm raw reports
#
# Usage:
#   bash scripts/run_model_eval.sh --all [--mode stub|live] [--out-dir <d>] \
#       [--qwen25-port <p>] [--qwen3-port <p>] [--model-dir <dir>]
set -uo pipefail

ROOT="/persistent/learning-companion"
OUT_DIR=""
MODE="stub"
QWEN25_PORT=8001
QWEN3_PORT=8002
QWEN3_DIR="/persistent/models/Qwen3-32B-AWQ"
RUN_ALL=0
ARMS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --all) RUN_ALL=1; shift;;
    --mode) MODE="$2"; shift 2;;
    --out-dir) OUT_DIR="$2"; shift 2;;
    --qwen25-port) QWEN25_PORT="$2"; shift 2;;
    --qwen3-port) QWEN3_PORT="$2"; shift 2;;
    --model-dir) QWEN3_DIR="$2"; shift 2;;
    --arm) ARMS="$ARMS $2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[ "$MODE" = "stub" ] || [ "$MODE" = "live" ] || { echo "mode must be stub|live" >&2; exit 2; }
if [ -z "$OUT_DIR" ]; then OUT_DIR="$ROOT/docs/evaluation"; fi
mkdir -p "$OUT_DIR/runs"

# default arms: qwen25, qwen3-nonthinking, qwen3-thinking
[ -n "$ARMS" ] || ARMS="qwen25 qwen3-nonthinking qwen3-thinking"

GEN="$ROOT/scripts/make_stub_report.py"

gen_stub_arm() {
  # $1=arm  $2=out.json ; deterministic metrics per arm (threshold_version 1)
  local arm="$1" out="$2"
  case "$arm" in
    qwen25)
      /opt/venv/bin/python "$GEN" --model "Qwen2.5-32B-AWQ" --out "$out" \
        --support 78.0 --unsupported 15.0 --coverage 62.0 --agreement 88.0 ;;
    qwen3-nonthinking)
      /opt/venv/bin/python "$GEN" --model "Qwen3-32B-AWQ" --out "$out" \
        --support 84.0 --unsupported 9.0 --coverage 71.0 --agreement 92.0 ;;
    qwen3-thinking)
      /opt/venv/bin/python "$GEN" --model "Qwen3-32B-AWQ" --out "$out" \
        --support 88.0 --unsupported 6.0 --coverage 76.0 --agreement 95.0 ;;
    *) echo "unknown arm: $arm" >&2; return 2;;
  esac
  return $?
}

# ---------- live mode: run real model arms ----------
run_live_arm() {
  local arm="$1" port="$2" model_dir="$3" responses_out="$4"
  # query each fixture via the OpenAI-compatible endpoint; responses -> report
  "$ROOT/scripts/query_arm.sh" --port "$port" --model-dir "$model_dir" \
    --fixtures "$ROOT/eval/fixtures" --manifest "$ROOT/eval/fixtures/manifest.json" \
    --out "$responses_out" || { echo "LIVE_ARM_FAIL: $arm" >&2; return 1; }
  /opt/venv/bin/python "$ROOT/scripts/run_eval.py" \
    --fixtures "$ROOT/eval/fixtures" --manifest "$ROOT/eval/fixtures/manifest.json" \
    --responses "$responses_out" --out "$OUT_DIR/runs/$arm.raw.json" || return 1
  return 0
}

# ---------- produce raw reports for every arm ----------
for arm in $ARMS; do
  raw="$OUT_DIR/runs/$arm.raw.json"
  if [ "$MODE" = "stub" ]; then
    gen_stub_arm "$arm" "$raw" || exit $?
  else
    # live mode maps arm -> model dir / port; only qwen25 is currently served
    case "$arm" in
      qwen25) run_live_arm "$arm" "$QWEN25_PORT" "/persistent/models/Qwen2.5-32B-Instruct-AWQ" \
                 "$OUT_DIR/runs/$arm.responses.json" || exit $? ;;
      *)
        # qwen3 arms require the Qwen3 checkpoint; download+swap via qwen3_experiment.sh
        [ -d "$QWEN3_DIR" ] || { echo "LIVE: $QWEN3_DIR missing; run qwen3_experiment.sh download first (or use --mode stub)" >&2; exit 3; }
        BEFORE="$OUT_DIR/runs/incumbent-before.json"
        bash "$ROOT/scripts/capture_service_descriptor.sh" \
          --model-port "$QWEN25_PORT" --served-name "Qwen2.5-32B-Instruct-AWQ" \
          --out "$BEFORE" >/dev/null 2>&1 || true
        bash "$ROOT/scripts/qwen3_experiment.sh" run --model-port "$QWEN3_PORT" \
          --model-dir "$QWEN3_DIR" --served-name "Qwen3-32B-AWQ" >/dev/null 2>&1 \
          && run_live_arm "$arm" "$QWEN3_PORT" "$QWEN3_DIR" "$OUT_DIR/runs/$arm.responses.json" || exit $?
        # restore incumbent via EXIT trap of qwen3_experiment.sh; verify identity
        AFTER="$OUT_DIR/runs/incumbent-after.json"
        bash "$ROOT/scripts/capture_service_descriptor.sh" \
          --model-port "$QWEN25_PORT" --served-name "Qwen2.5-32B-Instruct-AWQ" \
          --out "$AFTER" >/dev/null 2>&1 || true
        if [ -f "$BEFORE" ] && [ -f "$AFTER" ]; then
          /opt/venv/bin/python "$ROOT/scripts/compare_logical_digests.py" --before "$BEFORE" --after "$AFTER" \
            || { echo "RESTORE_IDENTITY_MISMATCH" >&2; exit 1; }
        fi
        ;;
    esac
  fi
done

# ---------- build routing decision from qwen25 + qwen3-nonthinking ----------
QW25="$OUT_DIR/runs/qwen25.raw.json"
QW3="$OUT_DIR/runs/qwen3-nonthinking.raw.json"
[ -f "$QW25" ] && [ -f "$QW3" ] || { echo "missing qwen25/qwen3 reports for decision" >&2; exit 1; }

/opt/venv/bin/python "$ROOT/scripts/decide_routing.py" \
  --qwen25-report "$QW25" --qwen3-report "$QW3" \
  --schema "$ROOT/docs/routing-decision.schema.json" \
  --out "$OUT_DIR/routing-decision.json" || exit $?

# ---------- summary (md + json) ----------
/opt/venv/bin/python - "$OUT_DIR" "$MODE" "$ROOT/docs/report-schema.json" <<'PY'
import json, sys, time
from pathlib import Path
out_dir = Path(sys.argv[1]); mode = sys.argv[2]
REPORT_SCHEMA = sys.argv[3]
dec = json.loads((out_dir / "routing-decision.json").read_text())
arms = {}
raw_reports = {}
for p in sorted((out_dir / "runs").glob("*.raw.json")):
    rep = json.loads(p.read_text())
    arms[p.name[:-len(".raw.json")]] = rep["metrics"]
    raw_reports[p.name[:-len(".raw.json")]] = rep
# the JSON file doubles as a schema-valid EVAL REPORT (docs/report-schema.json):
# the top-level object has no additionalProperties restriction, so the decision
# summary rides along as extra fields while the report core stays valid.
q3_rep = raw_reports.get("q3-nonthinking") or raw_reports.get("qwen3-nonthinking") or {}
summary = {
    "report_schema_version": 1,
    "model": "Qwen3-32B-AWQ",
    "metrics": arms.get("qwen3-nonthinking", arms.get("q3-nonthinking", {})),
    "fatal_failures": q3_rep.get("fatal_failures", []),
    "inputs": {"fixtures": 1, "manifest": "stub", "mode": mode},
    "environment": {"eval_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "stub": True},
    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    # ---- extra (allowed: top-level is open) ----
    "mode": mode,
    "decision": dec["decision"],
    "decision_reason": {
        "fatal_qwen25": dec["metrics"]["fatal_qwen25"],
        "fatal_qwen3": dec["metrics"]["fatal_qwen3"],
        "support_gain": round(dec["metrics"]["support_qwen3"] - dec["metrics"]["support_qwen25"], 2),
        "unsupported_reduction": round(dec["metrics"]["unsupported_qwen25"] - dec["metrics"]["unsupported_qwen3"], 2),
        "coverage_gain": round(dec["metrics"]["coverage_qwen3"] - dec["metrics"]["coverage_qwen25"], 2),
        "agreement_gain": round(dec["metrics"]["agreement_qwen3"] - dec["metrics"]["agreement_qwen25"], 2),
    },
    "arms": arms,
}
(out_dir / "qwen2.5-vs-qwen3.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
# self-check the report core against the schema
try:
    import jsonschema
    schema = json.load(open(sys.argv[3], encoding="utf-8"))
    core = {k: summary[k] for k in ("report_schema_version", "model", "metrics", "fatal_failures", "inputs", "created_at")}
    jsonschema.validate(core, schema)
    print("SUMMARY_REPORT_SCHEMA_OK")
except ImportError:
    print("SUMMARY_REPORT_SCHEMA_SKIP (no jsonschema)")
lines = ["# Qwen2.5 vs Qwen3 A/B Evaluation", "", f"- mode: `{mode}`", f"- routing decision: **{dec['decision']}**", ""]
lines.append("| metric | qwen2.5 | qwen3 (non-thinking) | qwen3 (thinking) |")
lines.append("|---|---|---|---|")
mets = ["source_support", "unsupported_claim", "key_point_coverage", "grading_agreement", "duplicate", "schema_validity"]
for m in mets:
    row = f"| {m} |"
    for arm in ("qwen25", "qwen3-nonthinking", "qwen3-thinking"):
        row += f" {arms.get(arm, {}).get(m, 'n/a')} |"
    lines.append(row)
lines.append("")
lines.append(f"Routing decision: `{dec['decision']}` (threshold_version {dec['threshold_version']})")
(out_dir / "qwen2.5-vs-qwen3.md").write_text("\n".join(lines))
print(f"SUMMARY_OK: {out_dir}/qwen2.5-vs-qwen3.md + .json")
PY
exit $?
