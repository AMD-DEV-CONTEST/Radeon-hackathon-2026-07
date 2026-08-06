# Local development environment

This document records the lightweight macOS maintenance environment used on
2026-08-05. It is intentionally separate from the official Linux Radeon/ROCm
validation environment described in the README and must not be cited as GPU
execution evidence.

## Recorded environment

| Item | Recorded value |
|---|---|
| Purpose | Local editing, linting, and targeted regression checks |
| Host platform | macOS arm64 |
| Environment prefix | Project-local `.venv` (Git-ignored) |
| Environment manager | Conda prefix environment |
| Python | `3.12.13` |
| Gradio | `5.50.0` |
| FastAPI | `0.141.1` |
| pytest | `8.4.2` |
| Ruff | `0.16.1` |
| Install mode used | Editable project with `.[dev]` |

The resolved application and test packages matched `requirements.lock` except
that Conda supplied `packaging==26.0` before pip resolution, while the formal
target lock records `packaging==26.2`. Future recreations should use the pinned
workflow below to eliminate that local bootstrap drift.

## Recreate the maintenance environment

Run from `submissions/track2-radeonstay`. The explicit interpreter paths avoid
depending on shell activation state.

```bash
test ! -e .venv
/opt/miniconda3/bin/conda create --prefix "$PWD/.venv" python=3.12 pip -y
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
```

For dependency development rather than a frozen reproduction, the bootstrap
used on 2026-08-05 was:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

Do not commit `.venv`, `.env`, databases, or generated runtime state.

## Lightweight maintenance gate

This gate deliberately checks only the high-value UI action-state, API action
boundary, cancellation, single-write capability, and restart-recovery paths.
Run the full suite only for release freezes or when a broad change requires it.

```bash
.venv/bin/python -m compileall -q src/radeonstay
.venv/bin/ruff check \
  src/radeonstay/contracts.py \
  src/radeonstay/orchestrator.py \
  src/radeonstay/api.py \
  src/radeonstay/ui.py \
  tests/test_api.py \
  tests/test_orchestrator.py \
  tests/test_ui.py
.venv/bin/python -m pytest -q \
  tests/test_ui.py::test_interaction_policy_exposes_only_state_valid_controls \
  tests/test_api.py::ApiBoundaryTests::test_action_only_confirm_cancel_resume_and_brief_endpoints \
  tests/test_orchestrator.py::RadeonStayOrchestratorTests::test_action_only_cancel_invalidates_preview_without_domain_write \
  tests/test_orchestrator.py::RadeonStayOrchestratorTests::test_one_turn_exposes_only_one_pending_write_capability \
  tests/test_orchestrator.py::RadeonStayOrchestratorTests::test_pending_state_recovers_without_restoring_capability_after_restart
```

Recorded result on 2026-08-05: compilation passed, the scoped Ruff check passed,
and all five targeted tests passed. The full test suite was not run as part of
this maintenance gate.

## Host-specific pytest failure

Do not use the base `/opt/miniconda3/bin/python` for this project on the recorded
workstation. Its Python 3.13.2 `readline` extension segfaulted during pytest
startup with exit code 139, first through `_pytest.capture` and then through
`pdb`/`rlcompleter`. The failure occurred before project test collection and was
therefore an interpreter environment fault, not a RadeonStay test failure.

Use `.venv/bin/python` from the Python 3.12 prefix above. Disabling pytest capture
or debugging plugins was diagnostic only and is not part of the maintained test
command.
