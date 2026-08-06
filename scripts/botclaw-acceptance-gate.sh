#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== BotClaw Acceptance Gate =="
echo "root: $ROOT"

# Prefer project venv Python (has pydantic), fallback to system python3.
if [ -x "$ROOT/apps/realtime/.venv/bin/python" ]; then
  PY_BIN="$ROOT/apps/realtime/.venv/bin/python"
elif [ -x "$ROOT/apps/api/.venv/bin/python" ]; then
  PY_BIN="$ROOT/apps/api/.venv/bin/python"
else
  PY_BIN="python3"
fi

echo
echo "== [1/4] Validate skills seed against BotClaw models =="
"$PY_BIN" "packages/botclaw-spec/scripts/validate_skills_seed.py"

echo
echo "== [2/4] Validate key BotClaw docs exist =="
test -f "packages/botclaw-spec/BotClaw-v0.9-draft.md"
test -f "packages/botclaw-spec/BotClaw-v0.9-freeze-point.md"
test -f "packages/botclaw-spec/docs/verb_taxonomy.md"
test -f "packages/botclaw-spec/docs/workflow_node_taxonomy.md"
echo "doc checks passed"

echo
echo "== [3/4] Validate safety schemas exist =="
test -f "packages/botclaw-spec/schemas/safety_envelope.schema.json"
test -f "packages/botclaw-spec/schemas/runtime_lease.schema.json"
test -f "packages/botclaw-spec/schemas/skill_run_event.schema.json"
echo "safety schema checks passed"

echo
echo "== [4/4] API registry smoke test =="
PYTHONPATH="$ROOT/apps/api" "$ROOT/apps/api/.venv/bin/python" - <<'PY'
from app.services import skill_registry

skills = skill_registry.list_skills()
assert len(skills) > 0, "skills registry is empty"
required = {"skill_id", "verb", "robot_type", "compatible_types", "params_schema"}
for i, s in enumerate(skills):
    missing = required - set(s.keys())
    if missing:
        raise AssertionError(f"skills[{i}] missing keys: {sorted(missing)}")
print(f"registry smoke passed: {len(skills)} skill(s)")
PY

echo
echo "BotClaw acceptance gate PASSED."
