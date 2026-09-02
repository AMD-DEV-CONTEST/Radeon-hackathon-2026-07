# AMD Linux Provider Acceptance Plan

## 1. Status and purpose

This is an executable acceptance plan for a prepared AMD Linux host. It is not
an acceptance record.

At authoring time:

- no command in this document had been executed on the target AMD Linux host;
- no Ollama model, ROCm result, performance result or Web result is claimed;
- every result remains `NOT RUN` until the named command and evidence are
  captured on the target host at the exact commit under test.

The acceptance goal is:

```text
inspect host and model identity
        |
        v
discover configured Ollama and exact model
        |
        v
explicitly select and persist Ollama
        |
        v
revalidate selection during Web startup
        |
        v
inject Ollama into the existing Web application
        |
        v
POST one bounded synthetic Event
        |
        v
verify SQLite Event/Decision and safe projections
```

This plan never downloads a model, changes ROCm, installs a driver or stores a
credential.

### Frozen release-candidate identity

The only source revision authorized for this acceptance run is:

| Item | Frozen value |
|---|---|
| Git tag | `v0.1.0-amd-linux-rc` |
| Commit SHA | `481d9a55256b8a829f0a5aa03e7f0603c92e866e` |
| Source branch at freeze | `codex/f03-d3-provider-runtime-orchestration` |

Do not substitute `main`, the current tip of a moving branch, or a shortened
SHA. The tag is the test selector and the full peeled commit SHA is the test
identity. This plan revision is release-control documentation published after
the source tag was frozen; it does not change the tagged product tree.

## 2. Acceptance boundary

In scope:

- Ubuntu/Linux, kernel, CPU, AMD GPU and memory identification;
- ROCm runtime/tool visibility;
- Ollama binary, service, version and loopback endpoint;
- exact model tag and full model digest;
- repository commit and clean/declared worktree state;
- Provider discovery and explicit selection;
- saved-selection revalidation by standard `web_api` startup;
- `GET /api/runtime`;
- one real Ollama inference through `POST /api/demo/events`;
- persisted Event and Decision;
- Workspace, Event, Digital Employee and Pulse projections;
- controlled unavailable, unconfigured and invalid-model failures.

Out of scope:

- model installation or `ollama pull`;
- ROCm/Ollama tuning;
- throughput or latency benchmarking;
- cloud-provider acceptance;
- equipment control, production diagnosis or a real incident;
- frontend feature changes;
- SQLite schema changes.

## 3. Required starting conditions

The operator must confirm:

- the host is the intended AMD Linux acceptance machine;
- the repository and commit to test are available locally;
- Python and project dependencies are already installed in the approved
  environment;
- Ollama is already installed and bound to loopback;
- the reviewed model is already present;
- no unrelated service uses ports `8090` through `8094`;
- the test description is synthetic and contains no customer or operational
  data.

Do not continue if the model tag or digest cannot be established. Record
`BLOCKED — MODEL IDENTITY UNKNOWN`; do not pull or substitute another model.

## 4. Evidence workspace

Run from the repository root:

```bash
set -euo pipefail

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="tmp/amd-linux-provider-acceptance-${RUN_ID}"
mkdir -p "$EVIDENCE_DIR"
chmod 700 "$EVIDENCE_DIR"
umask 077

export PYTHONPATH=src
export ALPHANOAH_ACCEPTANCE_EVIDENCE_DIR="$EVIDENCE_DIR"
```

`EVIDENCE_DIR` must remain outside commits. Before sharing it, review every
file for secrets, customer data and sensitive host paths.

Do not enable shell tracing (`set -x`). Do not print the process environment.

## 5. Commit and worktree identity

Fetch and enter the frozen candidate before creating any acceptance evidence:

```bash
git fetch origin tag v0.1.0-amd-linux-rc
git checkout --detach v0.1.0-amd-linux-rc

RC_SHA="$(git rev-parse HEAD)"
test "$RC_SHA" = "481d9a55256b8a829f0a5aa03e7f0603c92e866e"
test "$(git rev-parse 'v0.1.0-amd-linux-rc^{}')" = "$RC_SHA"
test -z "$(git status --porcelain)"
```

Stop with `BLOCKED - RELEASE CANDIDATE IDENTITY MISMATCH` if any command above
fails. Do not repair the mismatch by checking out `main` or another branch.

```bash
git rev-parse HEAD | tee "$EVIDENCE_DIR/commit-sha.txt"
git show -s --format='%H%n%ad%n%s' --date=iso-strict \
  | tee "$EVIDENCE_DIR/commit-description.txt"
git status --short | tee "$EVIDENCE_DIR/git-status-before.txt"
git branch --show-current | tee "$EVIDENCE_DIR/git-branch.txt"
```

Acceptance evidence must name the full SHA. A dirty worktree is not silently
accepted: either clean it without discarding user work, or list and justify
every difference in the final record.

## 6. OS, hardware and ROCm inventory

```bash
uname -a | tee "$EVIDENCE_DIR/uname.txt"
cat /etc/os-release | tee "$EVIDENCE_DIR/os-release.txt"
python3 --version 2>&1 | tee "$EVIDENCE_DIR/python-version.txt"
lscpu | tee "$EVIDENCE_DIR/lscpu.txt"
lspci -nn | grep -Ei 'vga|display|amd|ati' \
  | tee "$EVIDENCE_DIR/display-pci.txt"

command -v rocminfo | tee "$EVIDENCE_DIR/rocminfo-path.txt"
rocminfo > "$EVIDENCE_DIR/rocminfo.txt" 2>&1

command -v rocm-smi | tee "$EVIDENCE_DIR/rocm-smi-path.txt"
rocm-smi --showproductname --showdriverversion --showmeminfo vram \
  --showuse --showtemp --showpower \
  > "$EVIDENCE_DIR/rocm-smi-before.txt" 2>&1
```

If the installed `rocm-smi` does not support one of these flags, capture
`rocm-smi --help`, use the version-supported read-only equivalent and document
the substitution. Do not treat missing ROCm tooling as success merely because
Ollama responds.

## 7. Ollama service and model identity

Set only non-secret local identifiers:

```bash
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export MODEL_TAG="qwen3.5:9b"
```

Replace `MODEL_TAG` only with the reviewed tag intended for acceptance.

Capture the binary and API identity:

```bash
command -v ollama | tee "$EVIDENCE_DIR/ollama-path.txt"
ollama --version 2>&1 | tee "$EVIDENCE_DIR/ollama-version.txt"

curl --fail --silent --show-error \
  "$OLLAMA_BASE_URL/api/version" \
  | tee "$EVIDENCE_DIR/ollama-api-version.json"

curl --fail --silent --show-error \
  "$OLLAMA_BASE_URL/api/tags" \
  | tee "$EVIDENCE_DIR/ollama-tags.json"

ollama list | tee "$EVIDENCE_DIR/ollama-list.txt"
```

Extract the exact matching full digest without choosing the first returned
model:

```bash
python3 - "$EVIDENCE_DIR/ollama-tags.json" "$MODEL_TAG" \
  > "$EVIDENCE_DIR/model-identity.txt" <<'PY'
import json
import sys

path, expected = sys.argv[1:]
payload = json.load(open(path, encoding="utf-8"))
matches = [
    item for item in payload.get("models", [])
    if item.get("model", item.get("name")) == expected
]
if len(matches) != 1:
    raise SystemExit(
        f"expected exactly one installed model named {expected!r}; "
        f"found {len(matches)}"
    )
digest = matches[0].get("digest")
if isinstance(digest, str) and digest.lower().startswith("sha256:"):
    digest = digest[7:]
if (
    not isinstance(digest, str)
    or len(digest) != 64
    or any(character not in "0123456789abcdefABCDEF" for character in digest)
):
    raise SystemExit("model digest is missing or not a full SHA-256 value")
print(f"model_tag={expected}")
print(f"model_digest={digest.lower()}")
PY

MODEL_DIGEST="$(
  sed -n 's/^model_digest=//p' "$EVIDENCE_DIR/model-identity.txt"
)"
test "${#MODEL_DIGEST}" -eq 64
```

Optional additional model metadata may be captured with the installed Ollama
version's read-only `ollama show` command. Never run `ollama pull` in this
acceptance procedure.

## 8. Repository regression gate

Run the tests at the same commit before host acceptance:

```bash
python3 -m unittest discover -s tests \
  > "$EVIDENCE_DIR/python-tests.txt" 2>&1
python3 -m compileall -q src tests \
  > "$EVIDENCE_DIR/compileall.txt" 2>&1
git diff --check \
  > "$EVIDENCE_DIR/git-diff-check.txt" 2>&1

(
  cd frontend
  npm test -- --run
) > "$EVIDENCE_DIR/frontend-tests.txt" 2>&1

(
  cd frontend
  npm run typecheck
) > "$EVIDENCE_DIR/frontend-typecheck.txt" 2>&1

(
  cd frontend
  npm run build
) > "$EVIDENCE_DIR/frontend-build.txt" 2>&1
```

Record the exact test counts and any warnings in the final acceptance record.
Do not install or upgrade dependencies during this run without documenting that
the host ceased to be the prepared acceptance environment.

## 9. Build an isolated non-secret Provider configuration

Create an acceptance-only config under the ignored evidence directory:

```bash
ACCEPTANCE_CONFIG="$EVIDENCE_DIR/ai-runtime-acceptance.json"

python3 - "$ACCEPTANCE_CONFIG" "$OLLAMA_BASE_URL" "$MODEL_TAG" \
  "$MODEL_DIGEST" <<'PY'
import json
import sys

path, endpoint, model, digest = sys.argv[1:]
payload = {
    "schema_version": "ai-runtime-config-v1",
    "mode": "manual",
    "selected": None,
    "providers": {
        "fake": {"enabled": False},
        "ollama": {
            "enabled": True,
            "endpoint": endpoint,
            "model": model,
            "model_digest": digest,
            "timeout_seconds": 120.0,
        },
        "openai_compatible": {"enabled": False},
        "vllm": {"enabled": False},
    },
}
with open(path, "w", encoding="utf-8") as output:
    json.dump(payload, output, indent=2, sort_keys=True)
    output.write("\n")
PY

chmod 600 "$ACCEPTANCE_CONFIG"
```

The file contains no credential, database path, prompt or Runtime object.

## 10. Discovery must not select

Run read-only discovery:

```bash
python3 -m alphanoah_a1.demo provider \
  --config "$ACCEPTANCE_CONFIG" \
  --discovery-timeout 5 \
  discover \
  | tee "$EVIDENCE_DIR/provider-discovery.json"
```

Verify the exact model is reported as available:

```bash
python3 - "$EVIDENCE_DIR/provider-discovery.json" "$MODEL_TAG" \
  "$MODEL_DIGEST" <<'PY'
import json
import sys

path, expected_model, expected_digest = sys.argv[1:]
payload = json.load(open(path, encoding="utf-8"))
ollama = [
    item for item in payload["providers"]
    if item["provider"] == "ollama"
]
if len(ollama) != 1:
    raise SystemExit("discovery did not return exactly one Ollama result")
result = ollama[0]
if result["status"] != "AVAILABLE":
    raise SystemExit(f"Ollama is not AVAILABLE: {result['status']}")
if result["configured_model"] != expected_model:
    raise SystemExit("discovery returned a different configured model")
if expected_model not in result["available_models"]:
    raise SystemExit("configured model was not in the discovered model list")
if result["configured_model_digest"] != expected_digest:
    raise SystemExit("discovery did not retain the configured model digest")
if result["discovered_model_digest"] != expected_digest:
    raise SystemExit("discovery reported a different installed model digest")
if payload.get("mutated") is not False:
    raise SystemExit("discovery unexpectedly reported configuration mutation")
PY
```

Before explicit selection, Web/Doctor resolution must not choose Ollama merely
because it is the only available real candidate. Capture the controlled
unconfigured result:

```bash
set +e
python3 -m alphanoah_a1.demo doctor \
  --config "$ACCEPTANCE_CONFIG" \
  --discovery-timeout 5 \
  > "$EVIDENCE_DIR/doctor-unselected.out" \
  2> "$EVIDENCE_DIR/doctor-unselected.err"
DOCTOR_UNSELECTED_RC=$?
set -e
printf '%s\n' "$DOCTOR_UNSELECTED_RC" \
  > "$EVIDENCE_DIR/doctor-unselected.rc"
test "$DOCTOR_UNSELECTED_RC" -ne 0
```

The diagnostic must be controlled and must not mention Fake as a selected
fallback.

## 11. Explicit selection, persistence and revalidation

Explicitly select Ollama:

```bash
python3 -m alphanoah_a1.demo provider \
  --config "$ACCEPTANCE_CONFIG" \
  --discovery-timeout 5 \
  select ollama \
  | tee "$EVIDENCE_DIR/provider-select.json"
```

Confirm the persisted file contains `selected: ollama` and no secret value:

```bash
python3 - "$ACCEPTANCE_CONFIG" "$MODEL_TAG" <<'PY'
import json
import sys

path, expected_model = sys.argv[1:]
payload = json.load(open(path, encoding="utf-8"))
if payload.get("selected") != "ollama":
    raise SystemExit("explicit selection was not persisted")
settings = payload["providers"]["ollama"]
if settings.get("model") != expected_model:
    raise SystemExit("persisted model changed")
encoded = json.dumps(payload).lower()
for forbidden in ("authorization", "bearer ", "api_key_value", "password"):
    if forbidden in encoded:
        raise SystemExit(f"forbidden secret-shaped field found: {forbidden}")
PY
```

Re-run discovery/selection through Doctor and invoke one stateless model smoke
request:

```bash
python3 -m alphanoah_a1.demo doctor \
  --config "$ACCEPTANCE_CONFIG" \
  --discovery-timeout 5 \
  --smoke \
  | tee "$EVIDENCE_DIR/provider-doctor-smoke.json"
```

Required evidence:

- `selected_provider` is `ollama`;
- `selection_source` identifies the saved selection;
- discovery reports the exact configured model as available;
- `smoke_test` is `VALID`;
- `runtime_state_changed` is `false`;
- no credential or raw model response is present.

## 12. Web startup from saved selection

Clear process-local AI overrides so this run proves that the saved selection
affects Web composition:

```bash
unset ALPHANOAH_AI_PROVIDER
unset ALPHANOAH_AI_MODEL
unset ALPHANOAH_AI_BASE_URL
unset ALPHANOAH_AI_TIMEOUT_SECONDS
unset ALPHANOAH_AI_MODEL_DIGEST
unset ALPHANOAH_AI_CREDENTIAL_ENV
unset ALPHANOAH_OLLAMA_BASE_URL
unset ALPHANOAH_OLLAMA_MODEL
unset ALPHANOAH_OLLAMA_MODEL_DIGEST

WEB_DB="$EVIDENCE_DIR/acceptance-runtime.sqlite3"
WEB_PORT=8090

python3 -m alphanoah_a1.web_api \
  --db "$WEB_DB" \
  --port "$WEB_PORT" \
  --config "$ACCEPTANCE_CONFIG" \
  --discovery-timeout 5 \
  > "$EVIDENCE_DIR/web-api.log" 2>&1 &
WEB_PID=$!

cleanup() {
  kill "$WEB_PID" 2>/dev/null || true
  wait "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT
```

Wait for safe Runtime status:

```bash
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error \
    "http://127.0.0.1:${WEB_PORT}/api/runtime" \
    > "$EVIDENCE_DIR/runtime-status-before.json"; then
    break
  fi
  sleep 1
done

test -s "$EVIDENCE_DIR/runtime-status-before.json"
```

Assert the exact public contract:

```bash
python3 - "$EVIDENCE_DIR/runtime-status-before.json" "$MODEL_TAG" <<'PY'
import json
import sys

path, expected_model = sys.argv[1:]
payload = json.load(open(path, encoding="utf-8"))
expected_keys = {
    "version",
    "status",
    "provider",
    "model",
    "execution",
    "selection_source",
    "health",
}
if set(payload) != expected_keys:
    raise SystemExit(
        f"runtime status keys differ: {sorted(payload)}"
    )
expected = {
    "version": "runtime-status-v1",
    "status": "ready",
    "provider": "ollama",
    "model": expected_model,
    "execution": "local",
    "selection_source": "saved_config",
    "health": "healthy",
}
if payload != expected:
    raise SystemExit(f"unexpected runtime status: {payload!r}")
PY
```

## 13. Real synthetic Event through the selected Web Runtime

Create a bounded synthetic request. It is not a production incident:

```bash
REQUEST_ID="amd-linux-${RUN_ID}"

python3 - "$REQUEST_ID" > "$EVIDENCE_DIR/activation-request.json" <<'PY'
import json
import sys

print(json.dumps({
    "scenario_id": "synthetic-restaurant-aircon-a08",
    "description": (
        "Synthetic acceptance incident: A08 air conditioner remained on "
        "outside schedule. Not a real production incident."
    ),
    "request_id": sys.argv[1],
}))
PY

curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  --data-binary "@$EVIDENCE_DIR/activation-request.json" \
  "http://127.0.0.1:${WEB_PORT}/api/demo/events" \
  | tee "$EVIDENCE_DIR/activation-response.json"
```

Extract only public identifiers:

```bash
EVENT_ID="$(
  python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["event"]["event_id"])' \
    "$EVIDENCE_DIR/activation-response.json"
)"
DECISION_ID="$(
  python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["human_review"]["decision_id"])' \
    "$EVIDENCE_DIR/activation-response.json"
)"

printf 'event_id=%s\ndecision_id=%s\n' "$EVENT_ID" "$DECISION_ID" \
  | tee "$EVIDENCE_DIR/runtime-object-identities.txt"
```

Required response facts:

- projection version is `f03c-demo-v1`;
- Event status is `PENDING_HUMAN_REVIEW`;
- `analysis` and `human_review` are present;
- human review remains required;
- no Task or equipment action was silently created;
- the request did not expose a prompt or raw model response.

## 14. SQLite Event and Decision verification

Use existing read-only inspection commands against the same database:

```bash
python3 -m alphanoah_a1.demo \
  --db "$WEB_DB" \
  show event "$EVENT_ID" \
  | tee "$EVIDENCE_DIR/sqlite-event.json"

python3 -m alphanoah_a1.demo \
  --db "$WEB_DB" \
  show decision "$DECISION_ID" \
  | tee "$EVIDENCE_DIR/sqlite-decision.json"

TRACE_ID="$(
  python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["trace_id"])' \
    "$EVIDENCE_DIR/sqlite-event.json"
)"

python3 -m alphanoah_a1.demo \
  --db "$WEB_DB" \
  show trace "$TRACE_ID" \
  | tee "$EVIDENCE_DIR/sqlite-trace.txt"
```

Assert Provider identity and mandatory review:

```bash
python3 - "$EVIDENCE_DIR/sqlite-event.json" \
  "$EVIDENCE_DIR/sqlite-decision.json" "$EVENT_ID" "$MODEL_TAG" <<'PY'
import json
import sys

event_path, decision_path, event_id, model = sys.argv[1:]
event = json.load(open(event_path, encoding="utf-8"))
decision = json.load(open(decision_path, encoding="utf-8"))
if event["event_id"] != event_id:
    raise SystemExit("SQLite Event identity differs")
if event["status"] != "PENDING_HUMAN_REVIEW":
    raise SystemExit(f"unexpected Event state: {event['status']}")
if decision["event_id"] != event_id:
    raise SystemExit("Decision is not attached to the Event")
if decision["requires_human_review"] is not True:
    raise SystemExit("Decision bypassed mandatory human review")
if decision["model_or_rule"] != f"ollama:{model}":
    raise SystemExit(
        f"Decision did not use expected Ollama model: "
        f"{decision['model_or_rule']!r}"
    )
PY
```

The exact model digest remains host/model evidence even if the business
Decision stores only the provider/model tag.

## 15. Projection verification

Read each safe projection after activation:

```bash
curl --fail --silent --show-error \
  "http://127.0.0.1:${WEB_PORT}/api/workspace" \
  | tee "$EVIDENCE_DIR/projection-workspace.json"

curl --fail --silent --show-error \
  "http://127.0.0.1:${WEB_PORT}/api/events" \
  | tee "$EVIDENCE_DIR/projection-events.json"

curl --fail --silent --show-error \
  "http://127.0.0.1:${WEB_PORT}/api/digital-employees" \
  | tee "$EVIDENCE_DIR/projection-digital-employees.json"

curl --fail --silent --show-error \
  "http://127.0.0.1:${WEB_PORT}/api/pulse" \
  | tee "$EVIDENCE_DIR/projection-pulse.json"

curl --fail --silent --show-error \
  "http://127.0.0.1:${WEB_PORT}/api/runtime" \
  | tee "$EVIDENCE_DIR/runtime-status-after.json"
```

Verify:

- Workspace and Event feed contain `EVENT_ID`;
- Workspace active Event matches the activation;
- Digital Employee projection reports the matched responsibility and current
  Event without inventing a Task;
- Pulse points to the same Event and reflects its Notification;
- Runtime status remains Ollama, ready, local and `saved_config`;
- projection payloads contain no prompt, Authorization header, API key,
  database/config path, traceback or raw provider response.

## 16. AMD observation after inference

Capture the same read-only GPU snapshot after the real Event:

```bash
rocm-smi --showproductname --showdriverversion --showmeminfo vram \
  --showuse --showtemp --showpower \
  > "$EVIDENCE_DIR/rocm-smi-after.txt" 2>&1
```

The before/after snapshots prove only sampled host observations. They are not a
continuous benchmark and must not be used to claim a performance number.

## 17. Explicit command-line precedence check

Use a separate process and database to prove command-line values have highest
precedence. Do not disturb the accepted process until its evidence is complete.

```bash
CLI_DB="$EVIDENCE_DIR/cli-precedence.sqlite3"

python3 -m alphanoah_a1.web_api \
  --db "$CLI_DB" \
  --port 8091 \
  --config "$ACCEPTANCE_CONFIG" \
  --provider ollama \
  --model "$MODEL_TAG" \
  --base-url "$OLLAMA_BASE_URL" \
  --timeout-seconds 120 \
  --model-digest "$MODEL_DIGEST" \
  --discovery-timeout 5 \
  > "$EVIDENCE_DIR/web-cli-precedence.log" 2>&1 &
CLI_WEB_PID=$!

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error \
    "http://127.0.0.1:8091/api/runtime" \
    > "$EVIDENCE_DIR/runtime-status-command-line.json"; then
    break
  fi
  sleep 1
done

kill "$CLI_WEB_PID" 2>/dev/null || true
wait "$CLI_WEB_PID" 2>/dev/null || true
```

Required status:

- provider/model match the explicit values;
- `selection_source` is `command_line`;
- no CLI value was persisted back into `ACCEPTANCE_CONFIG`.

## 18. Explicit environment precedence check

Use only documented generic AI environment variables:

```bash
export ALPHANOAH_AI_PROVIDER=ollama
export ALPHANOAH_AI_MODEL="$MODEL_TAG"
export ALPHANOAH_AI_BASE_URL="$OLLAMA_BASE_URL"
export ALPHANOAH_AI_TIMEOUT_SECONDS=120
export ALPHANOAH_AI_MODEL_DIGEST="$MODEL_DIGEST"
unset ALPHANOAH_AI_CREDENTIAL_ENV

python3 -m alphanoah_a1.web_api \
  --db "$EVIDENCE_DIR/environment-precedence.sqlite3" \
  --port 8092 \
  --config "$ACCEPTANCE_CONFIG" \
  --discovery-timeout 5 \
  > "$EVIDENCE_DIR/web-environment-precedence.log" 2>&1 &
ENV_WEB_PID=$!

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error \
    "http://127.0.0.1:8092/api/runtime" \
    > "$EVIDENCE_DIR/runtime-status-environment.json"; then
    break
  fi
  sleep 1
done

kill "$ENV_WEB_PID" 2>/dev/null || true
wait "$ENV_WEB_PID" 2>/dev/null || true

unset ALPHANOAH_AI_PROVIDER
unset ALPHANOAH_AI_MODEL
unset ALPHANOAH_AI_BASE_URL
unset ALPHANOAH_AI_TIMEOUT_SECONDS
unset ALPHANOAH_AI_MODEL_DIGEST
```

Required status:

- provider/model match the environment values;
- `selection_source` is `environment`;
- the saved configuration is unchanged.

The legacy `ALPHANOAH_OLLAMA_BASE_URL`, `ALPHANOAH_OLLAMA_MODEL` and
`ALPHANOAH_OLLAMA_MODEL_DIGEST` variables remain compatibility inputs, but new
acceptance evidence uses the generic `ALPHANOAH_AI_*` names.

## 19. Controlled failure scenarios

Each case must fail closed without switching to a real alternate Provider or
Fake. Use a separate database and port.

### 19.1 Unselected discovery candidates

Use the pre-selection version of the acceptance config, or produce another
valid config with `selected: null`:

```bash
UNSELECTED_CONFIG="$EVIDENCE_DIR/ai-runtime-unselected.json"
python3 - "$ACCEPTANCE_CONFIG" "$UNSELECTED_CONFIG" <<'PY'
import json
import sys

source, target = sys.argv[1:]
payload = json.load(open(source, encoding="utf-8"))
payload["selected"] = None
with open(target, "w", encoding="utf-8") as output:
    json.dump(payload, output, indent=2, sort_keys=True)
    output.write("\n")
PY

python3 -m alphanoah_a1.web_api \
  --db "$EVIDENCE_DIR/unselected.sqlite3" \
  --port 8093 \
  --config "$UNSELECTED_CONFIG" \
  --discovery-timeout 5 \
  > "$EVIDENCE_DIR/unselected-web.log" 2>&1 &
UNSELECTED_PID=$!

for attempt in $(seq 1 15); do
  if curl --fail --silent --show-error \
    "http://127.0.0.1:8093/api/runtime" \
    > "$EVIDENCE_DIR/unselected-runtime-status.json"; then
    break
  fi
  sleep 1
done

python3 - "$EVIDENCE_DIR/unselected-runtime-status.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload["status"] != "unconfigured":
    raise SystemExit(f"expected unconfigured, got {payload!r}")
if payload["provider"] is not None:
    raise SystemExit("unselected discovery chose a Provider")
if payload["selection_source"] != "none":
    raise SystemExit("unselected discovery reported a selection source")
PY

UNSELECTED_HTTP="$(
  curl --silent --show-error \
    -o "$EVIDENCE_DIR/unselected-activation-response.json" \
    -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    --data-binary "@$EVIDENCE_DIR/activation-request.json" \
    "http://127.0.0.1:8093/api/demo/events"
)"
printf '%s\n' "$UNSELECTED_HTTP" \
  > "$EVIDENCE_DIR/unselected-activation-http-status.txt"
test "$UNSELECTED_HTTP" = "503"

python3 -m alphanoah_a1.demo \
  --db "$EVIDENCE_DIR/unselected.sqlite3" \
  list events \
  | tee "$EVIDENCE_DIR/unselected-events.txt"
grep -Fx 'No events found.' "$EVIDENCE_DIR/unselected-events.txt"

kill "$UNSELECTED_PID" 2>/dev/null || true
wait "$UNSELECTED_PID" 2>/dev/null || true
```

The status boundary may start, but it must not report `ready`, run analysis or
select Fake/Ollama automatically. The Web handler must reject activation before
Runtime mutation, creating zero Events and zero Decisions.

### 19.2 Configured model missing

```bash
python3 -m alphanoah_a1.web_api \
  --db "$EVIDENCE_DIR/missing-model.sqlite3" \
  --port 8094 \
  --provider ollama \
  --base-url "$OLLAMA_BASE_URL" \
  --model "alphanoah-model-that-must-not-exist:acceptance" \
  --timeout-seconds 30 \
  --discovery-timeout 5 \
  > "$EVIDENCE_DIR/missing-model-web.log" 2>&1 &
MISSING_MODEL_PID=$!

for attempt in $(seq 1 15); do
  if curl --fail --silent --show-error \
    "http://127.0.0.1:8094/api/runtime" \
    > "$EVIDENCE_DIR/missing-model-runtime-status.json"; then
    break
  fi
  sleep 1
done

python3 - "$EVIDENCE_DIR/missing-model-runtime-status.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload["status"] not in {"invalid_configuration", "unavailable"}:
    raise SystemExit(f"missing model did not fail closed: {payload!r}")
if payload["provider"] != "ollama":
    raise SystemExit("missing model switched Provider")
if payload["selection_source"] != "command_line":
    raise SystemExit("missing model lost explicit selection source")
PY

MISSING_MODEL_HTTP="$(
  curl --silent --show-error \
    -o "$EVIDENCE_DIR/missing-model-activation-response.json" \
    -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    --data-binary "@$EVIDENCE_DIR/activation-request.json" \
    "http://127.0.0.1:8094/api/demo/events"
)"
printf '%s\n' "$MISSING_MODEL_HTTP" \
  > "$EVIDENCE_DIR/missing-model-activation-http-status.txt"
test "$MISSING_MODEL_HTTP" = "503"

python3 -m alphanoah_a1.demo \
  --db "$EVIDENCE_DIR/missing-model.sqlite3" \
  list events \
  | tee "$EVIDENCE_DIR/missing-model-events.txt"
grep -Fx 'No events found.' "$EVIDENCE_DIR/missing-model-events.txt"

kill "$MISSING_MODEL_PID" 2>/dev/null || true
wait "$MISSING_MODEL_PID" 2>/dev/null || true
```

Required: status-only unavailable mode, no model substitution, no Fake and no
successful business analysis. Activation must be rejected before creating an
Event or Decision.

### 19.3 Provider endpoint unavailable

```bash
python3 -m alphanoah_a1.web_api \
  --db "$EVIDENCE_DIR/unavailable-provider.sqlite3" \
  --port 8093 \
  --provider ollama \
  --base-url "http://127.0.0.1:65534" \
  --model "$MODEL_TAG" \
  --timeout-seconds 10 \
  --discovery-timeout 2 \
  > "$EVIDENCE_DIR/unavailable-provider-web.log" 2>&1 &
UNAVAILABLE_PID=$!

for attempt in $(seq 1 15); do
  if curl --fail --silent --show-error \
    "http://127.0.0.1:8093/api/runtime" \
    > "$EVIDENCE_DIR/unavailable-provider-runtime-status.json"; then
    break
  fi
  sleep 1
done

python3 - "$EVIDENCE_DIR/unavailable-provider-runtime-status.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload["status"] != "unavailable":
    raise SystemExit(f"expected unavailable, got {payload!r}")
if payload["provider"] != "ollama":
    raise SystemExit("unavailable Ollama switched Provider")
if payload["selection_source"] != "command_line":
    raise SystemExit("unavailable Ollama lost explicit selection source")
PY

UNAVAILABLE_HTTP="$(
  curl --silent --show-error \
    -o "$EVIDENCE_DIR/unavailable-activation-response.json" \
    -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    --data-binary "@$EVIDENCE_DIR/activation-request.json" \
    "http://127.0.0.1:8093/api/demo/events"
)"
printf '%s\n' "$UNAVAILABLE_HTTP" \
  > "$EVIDENCE_DIR/unavailable-activation-http-status.txt"
test "$UNAVAILABLE_HTTP" = "503"

python3 -m alphanoah_a1.demo \
  --db "$EVIDENCE_DIR/unavailable-provider.sqlite3" \
  list events \
  | tee "$EVIDENCE_DIR/unavailable-provider-events.txt"
grep -Fx 'No events found.' "$EVIDENCE_DIR/unavailable-provider-events.txt"

kill "$UNAVAILABLE_PID" 2>/dev/null || true
wait "$UNAVAILABLE_PID" 2>/dev/null || true
```

Required: explicit unavailable status, controlled 503, no
traceback/path/response-body leakage, no Fake, and zero Events/Decisions.

### 19.4 Saved selection becomes unavailable

Stop only the acceptance Ollama service under the host operator's approved
procedure, or perform this case against an isolated unreachable endpoint in a
copied config. Restart Web using the saved selection.

Required: startup revalidates and fails unavailable; it does not use stale trust
and does not rewrite the saved selection.

Do not stop a shared Ollama service without authorization.

### 19.5 Explicit Fake boundary

On an isolated port, `--provider fake` must succeed and `/api/runtime` must
report:

- `provider: fake`;
- synthetic/demo execution;
- `selection_source: command_line`.

The same startup without `--provider fake` must not choose Fake.

### 19.6 Missing compatible credential reference

For an approved test-only OpenAI-compatible endpoint, configure only the name
of an unset credential environment variable. Discovery/startup must return a
controlled missing-credential result without sending a request or printing the
environment. Do not use a real cloud credential for this negative test.

## 20. Secret and sensitive-data review

Before packaging evidence:

```bash
grep -RniE \
  --exclude='sensitive-pattern-review.txt' \
  '(Authorization:|Bearer[[:space:]]+[A-Za-z0-9._-]+|password[[:space:]]*[:=]|api[_-]?key[[:space:]]*[:=])' \
  "$EVIDENCE_DIR" \
  > "$EVIDENCE_DIR/sensitive-pattern-review.txt" || true
```

Review every match manually. An environment-variable name such as
`ALPHANOAH_AI_CREDENTIAL_ENV` may be documented; its value must not be.

Also remove or redact:

- customer or real incident text;
- home-directory usernames if not needed;
- credential values and headers;
- prompts and raw model responses;
- local database/config absolute paths;
- unrelated process/environment output.

Never attach `env`, `printenv`, a shell history or a process dump.

## 21. Evidence manifest

After review, generate hashes without hashing the manifest into itself:

```bash
(
  cd "$EVIDENCE_DIR"
  find . -maxdepth 1 -type f ! -name SHA256SUMS \
    -print0 | sort -z | xargs -0 sha256sum
) > "$EVIDENCE_DIR/SHA256SUMS"
```

The final evidence package must contain:

- full commit SHA, branch and worktree declaration;
- OS/kernel/CPU/GPU inventory;
- ROCm paths and before/after snapshots;
- Ollama binary/API versions;
- exact model tag and full digest;
- discovery output before selection;
- proof that unselected discovery did not auto-select;
- explicit selection and persisted non-secret config;
- Doctor smoke result;
- saved-selection Web startup log;
- `/api/runtime` before and after Event;
- activation request/response using synthetic data;
- read-only SQLite Event, Decision and trace;
- Workspace, Event, Digital Employee and Pulse projections;
- CLI and environment precedence results;
- each controlled failure result and exit code;
- secret-review result;
- file hashes.

## 22. Acceptance record

Complete this table only after execution:

| Gate | Result | Evidence | Notes |
|---|---|---|---|
| Exact commit/worktree recorded | NOT RUN |  |  |
| OS/AMD GPU/ROCm identified | NOT RUN |  |  |
| Ollama loopback identity verified | NOT RUN |  |  |
| Model tag and full digest verified | NOT RUN |  |  |
| Discovery found exact configured model | NOT RUN |  |  |
| Discovery did not auto-select | NOT RUN |  |  |
| Explicit selection persisted without secret | NOT RUN |  |  |
| Saved selection revalidated | NOT RUN |  |  |
| Doctor real Ollama smoke valid | NOT RUN |  |  |
| Web Runtime reports saved Ollama | NOT RUN |  |  |
| Synthetic Event reached real Ollama | NOT RUN |  |  |
| SQLite Event/Decision/provider identity valid | NOT RUN |  |  |
| Workspace/Event/Employee/Pulse projections valid | NOT RUN |  |  |
| CLI/environment precedence valid | NOT RUN |  |  |
| No silent Fake/alternate fallback | NOT RUN |  |  |
| Controlled failures safe | NOT RUN |  |  |
| Evidence reviewed for secrets | NOT RUN |  |  |
| Repository regression suite passed | NOT RUN |  |  |

Allowed final verdicts:

- `ACCEPTED ON AMD LINUX`;
- `REJECTED — PROVIDER OR RUNTIME FAILURE`;
- `BLOCKED — HOST OR EVIDENCE INCOMPLETE`.

Do not use `ACCEPTED` if any required gate remains `NOT RUN`, lacks evidence or
was executed at a different commit.
