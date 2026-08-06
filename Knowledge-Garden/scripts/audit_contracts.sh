#!/bin/bash
# audit_contracts.sh — drift-proof API contract parity check (Todo 5).
#
# 1. Export the OpenAPI JSON from the CURRENT FastAPI app, canonicalize (sorted keys).
# 2. Diff against the checked-in docs/openapi-snapshot.json.
# 3. Generate TypeScript client types from the freshly exported canonical snapshot.
# 4. Diff against the checked-in web/src/lib/api.gen.ts.
# Fails nonzero on either diff (backend drift OR snapshot-only edit).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-/opt/venv/bin/python}"
SNAPSHOT="$ROOT/docs/openapi-snapshot.json"
GEN="$ROOT/web/src/lib/api.gen.ts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1+2: export + canonicalize + diff snapshot
"$PYTHON" - "$TMP/current.json" <<'PY' || exit 1
import json, sys
sys.path.insert(0, "/persistent/learning-companion")
from app.main import app
spec = app.openapi()
json.dump(spec, open(sys.argv[1], "w"), ensure_ascii=False, sort_keys=True, indent=2)
PY
if [ -f "$SNAPSHOT" ]; then
  if ! diff -q "$SNAPSHOT" "$TMP/current.json" >/dev/null; then
    echo "CONTRACT_DRIFT: OpenAPI snapshot differs from current app schema"
    echo "  -> run 'python3 - <<PY ... app.openapi() ...' to refresh docs/openapi-snapshot.json"
    exit 1
  fi
else
  cp "$TMP/current.json" "$SNAPSHOT"
  echo "snapshot created: $SNAPSHOT"
fi

# 3+4: generate TS types from the fresh snapshot, diff against checked-in gen
"$PYTHON" - "$TMP/current.json" "$TMP/api.gen.ts" <<'PY' || exit 1
import json, sys, re
spec = json.load(open(sys.argv[1]))
schemas = spec.get("components", {}).get("schemas", {})
lines = ["// AUTO-GENERATED from docs/openapi-snapshot.json — do not edit by hand.", "// Regenerate via scripts/audit_contracts.sh.", ""]
def js_type(name):
    return name  # simple 1:1 (schemas are already typed)
for name in sorted(schemas):
    schema = schemas[name]
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    lines.append(f"export interface {name} {{")
    for pn in sorted(props):
        p = props[pn]
        t = p.get("type", "any")
        if t == "array":
            items = p.get("items", {}).get("$ref", "any").split("/")[-1]
            t = f"{items}[]"
        elif "$ref" in p:
            t = p["$ref"].split("/")[-1]
        elif t == "integer":
            t = "number"
        elif t == "object":
            t = "Record<string, unknown>"
        opt = "" if pn in required else "?"
        lines.append(f"  {pn}{opt}: {t}")
    lines.append("}")
    lines.append("")
open(sys.argv[2], "w").write("\n".join(lines))
print("types generated")
PY
if [ -f "$GEN" ]; then
  if ! diff -q "$GEN" "$TMP/api.gen.ts" >/dev/null; then
    echo "CONTRACT_DRIFT: TypeScript types differ from current OpenAPI snapshot"
    diff "$GEN" "$TMP/api.gen.ts" | head -40
    exit 1
  fi
else
  cp "$TMP/api.gen.ts" "$GEN"
  echo "generated types created: $GEN"
fi

echo "AUDIT_CONTRACTS_OK: backend schema == snapshot == generated TS types"
exit 0
