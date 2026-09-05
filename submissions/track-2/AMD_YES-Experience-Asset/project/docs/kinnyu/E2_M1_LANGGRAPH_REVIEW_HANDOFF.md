# E2 / M1 LangGraph Review and W7900 Handoff

Status: `LOCAL_IMPLEMENTATION_COMPLETE / COMMIT_BINDING_PENDING / W7900_ASSIGNED_TO_KINNYUWW`

Issue: [#15](https://github.com/kinnyuww/amd-devmaster-track2-agent/issues/15)

Implementation PR: [#16](https://github.com/kinnyuww/amd-devmaster-track2-agent/pull/16)

Architecture and ownership plan:
[#17](https://github.com/kinnyuww/amd-devmaster-track2-agent/pull/17)

## 1. What Eas000n has completed locally

- Frozen workflow contract and dependency combination.
- Real eight-node compiled production LangGraph.
- Separate SQLite checkpointer and canonical Asset Repository authority.
- Production route injection with no Fake Loop import or call.
- Typed minimal state allowlist and sanitized checkpoint/Trace behavior.
- Allow, deny, model/format failure and stale/incompatible branches.
- Missing and corrupt checkpoint safe-stop.
- Restart without duplicate model or tool effects.
- Runtime-identity mismatch safe-stop across code/model/server changes.
- Started-but-indeterminate effects are not replayed.
- Direct and indirect imported-instruction rejection with zero tool dispatch.
- Cancellation, unexpected tool exception and transient repository exception
  terminalization.
- Idempotent terminal write.
- Durable `CODE_COMMIT` identity for review/evidence runs.
- Backend, frontend, real loopback browser and repository gates.

Frozen workflow identity:

```text
workflow_version = experience-asset/e2-m1/v1
topology_hash = 2ed5001b1c7bf177335e0bbff59e964b115c1a90c8454f3784e9e695e3cbd707
```

## 2. Local review commands

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
bash -n scripts/*.sh
python3 -m py_compile scripts/*.py
python3 -m unittest discover -s qa/tests -v
bash qa/gates/pr_gate.sh --mode contract
.venv/bin/python scripts/export_contracts.py --check
git diff --check
```

```bash
cd web
npm run verify:contracts
npm run test
npm run typecheck
npm run lint
npm run build
```

For the real local web path, start FastAPI on `127.0.0.1:8080` with separate
asset and workflow databases, then run:

```bash
E2E_LIVE_BASE_URL=http://127.0.0.1:8080 \
VITE_PROXY_TARGET=http://127.0.0.1:8080 \
npm run e2e
```

Latest local candidate result:

```text
backend pytest       99/99
public QA             31/31
frontend Vitest       95/95
contract provenance   15/15
live Playwright       17/17
public artifact gate  PASS (chair_incomplete)
Ruff / contract gate / contract export / typecheck / lint / build PASS
```

The bounded Git evidence artifacts are under
`evidence/milestones/e2-m1-langgraph-local/20260728T102918Z/artifacts/` and
include the public asset, state-derived progress, public M1 workspace,
current-source retrieval Trace, checkpoint-linked node Trace, hash manifest
and inspected live UI capture.

## 3. Quality-owner review focus

The checkpoint-2 review should verify:

1. the compiled graph exposes all eight independent nodes;
2. `create_app()` compiles once and injects the same runner into the route;
3. the route and production graph do not import or call
   `DurableFakeAgentLoop`;
4. graph checkpoints contain no source text, raw prompt/response or complete
   canonical asset;
5. SQLite Asset Repository is canonical truth and the LangGraph saver is the
   sole production cursor authority;
6. allow, deny, model failure and stale/incompatible paths reach the expected
   terminal;
7. restart does not duplicate model or tool effects;
8. an indeterminate started effect is not replayed;
9. model/server/config/code identity drift prevents resume;
10. cancellation and unexpected node failures do not leave incomplete runs;
11. direct and indirect imported instructions cannot expand tool permission;
12. node Trace binds workflow, topology, edge, checkpoint, policy, tool,
   verification, terminal and finding metadata;
13. a review/evidence run stores the exact PR head in `code_commit`.

The prior checkpoint-2 packet predates the real LangGraph implementation. It
must not be reused as proof for the corrected topology.

## 4. Bounded W7900 handoff to kinnyuww

W7900 work begins only from the exact reviewed PR #16 head. In the persistent
checkout:

```bash
cd /workspace/amd-track2-agent/repo
git rev-parse HEAD
export CODE_COMMIT="$(git rev-parse HEAD)"
bash scripts/verify_remote_dev.sh
bash scripts/verify_rocm_env.sh
```

Keep vLLM and the Agent in their separate persistent environments. Verify the
approved immutable model snapshot before serving:

```bash
python3 scripts/verify_model_snapshot.py \
  --manifest config/models/qwen2.5-14b-instruct.modelscope.json \
  --model-dir /workspace/amd-track2-agent/models/Qwen2.5-14B-Instruct-3957bf39753c
```

Start the frozen loopback-only serving profile and verify structured proposal
compatibility:

```bash
bash scripts/serve_vllm.sh
python3 scripts/verify_vllm_tool_call.py --model Qwen2.5-14B-Instruct
```

Start the Agent with persistent and separate databases:

```bash
source /workspace/amd-track2-agent/venvs/agent/bin/activate
export EXPERIENCE_ASSET_DB=/workspace/amd-track2-agent/data/experience_asset.sqlite3
export EXPERIENCE_WORKFLOW_DB=/workspace/amd-track2-agent/data/experience_asset.workflow.sqlite3
export OPENAI_BASE_URL=http://127.0.0.1:8000/v1
export SERVED_MODEL_NAME=Qwen/Qwen2.5-14B-Instruct
uvicorn app.experience_asset.api.main:app --host 127.0.0.1 --port 8080
```

Do not expose either service to the internet. The W7900 packet must bind the
same exact values:

- PR #16 commit and clean-tree status;
- workflow version and topology hash above;
- W7900, driver, ROCm, PyTorch and vLLM identities;
- immutable model revision, snapshot verification and BF16 serving arguments;
- fixture/scenario identity;
- model proposal, Runtime policy, zero-or-one tool effect, verification,
  terminal state and checkpoint-linked sanitized node Trace;
- success, denial/failure and restart observations;
- Serving Reference S1 measurements and every retained failure;
- rollback and remaining risks.

Run before stopping or destroying the instance:

```bash
bash scripts/pre_stop_checkpoint.sh
```

## 5. Promotion boundary

Local green tests do not promote E2. E2 becomes eligible only after:

1. an authorized clean implementation commit and exact-head local packet;
2. independent checkpoint-2 acceptance by `kinnyuww`;
3. W7900 Serving Reference S1 and commit-bound Vertical Slice V1;
4. checkpoint-3 quality decision;
5. approved merge and explicit E2 promotion.

E3 may continue bounded contract/Mock/fixture preparation, but it must not
integrate unmerged E2 state.
