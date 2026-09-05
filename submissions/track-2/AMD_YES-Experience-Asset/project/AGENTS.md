# Repository Instructions

## Purpose

This repository is the reproducible workspace for a three-person AMD AI
DevMaster Hackathon Track 2 project. The core inference path must run on the
Radeon Cloud W7900 through ROCm. Keep the application useful, private by
default, measurable, and easy for a reviewer to reproduce.

## Persistent paths

- Treat `/workspace` as the only persistent cloud filesystem.
- Use `/workspace/amd-track2-agent/repo` for the integration checkout.
- Put model caches, virtual environments, logs, benchmarks, and public/private
  data under `/workspace/amd-track2-agent`.
- Never assume that `/root`, `~`, or `/tmp` survives a pod rebuild.
- Persistent volume is not a backup. GitHub is the source of truth for source
  code; approved external storage is the source of truth for large artifacts.

## Architecture boundaries

- Keep the Agent application and vLLM in separate Python environments.
- vLLM owns model loading and inference serving.
- The Agent runtime owns workflow state, tool allowlists, argument validation,
  approvals, retries, timeouts, audit, and privacy controls.
- Model tool-call output is a proposal. It never grants execution permission.
- Keep current-experience grounding separate from cross-asset RAG. Current
  source spans and prior versions of the same asset may support M1-M4, but no
  historical Experience Asset may be searched until the current Knowledge Card
  reaches the explicit readiness gate after M4. Candidate discovery is
  summary-only; detailed historical retrieval requires the user's confirmation
  of the selected relation and must not silently rewrite the current asset.
- Do not add a closed remote model API to the core inference path.
- AMD shared model APIs may be used only as bounded development workers. They
  must not receive private project data or replace the submitted local model.
- Bind private inference and development services to `127.0.0.1` by default.
- Do not run `rc-tunnel expose` or otherwise publish a service to the internet
  unless the user explicitly authorizes that publication after authentication
  and the local service have been verified.

## Working rules

1. Read `spec/README.md` and complete `spec/AGENT_ALIGNMENT.md` before proposing
   or performing work. Also read `README.md`,
   `docs/COMPETITION_AND_GROUP_SUMMARY.md`,
   `docs/DEVELOPMENT_ENVIRONMENT.md`, and `docs/TEAM_GIT_WORKFLOW.md` before
   broad changes. Every work package must state its Track 2 relevance and
   evidence/submission impact; `none` requires a reason.
2. Make the smallest coherent change that satisfies the current task.
3. Add or update tests when behavior changes.
4. Run the relevant checks before presenting work as complete.
5. Update documentation when commands, paths, dependencies, or architecture
   change.
6. Keep generated models, datasets, caches, secrets, and credentials out of Git.

## Git safety

- Work on a task branch; do not develop directly on `main`.
- Do not run `git commit`, `git push`, merge, rebase, force-push, open a Pull
  Request, or modify GitHub settings unless the user explicitly requests that
  action in the current task.
- Never use `--force` or `--force-with-lease` without explicit approval.
- Secondary coding workers never commit, push, merge, rebase, open Pull
  Requests, or change remotes. The primary agent reviews their diff and tests.
- Preserve user changes and unrelated dirty files.
- Before a pod is destroyed, run `bash scripts/pre_stop_checkpoint.sh`.

## Required checks

For repository-only changes:

```bash
bash -n scripts/*.sh
python3 -m py_compile scripts/*.py
python3 -m unittest discover -s qa/tests -v
bash qa/gates/pr_gate.sh --mode contract
```

On Radeon Cloud:

```bash
bash scripts/verify_remote_dev.sh
bash scripts/verify_rocm_env.sh
```

For Agent code, use the persistent environment:

```bash
source /workspace/amd-track2-agent/venvs/agent/bin/activate
pytest
ruff check .
```

## Definition of done

A change is done only when:

- behavior and acceptance criteria are demonstrated;
- relevant checks pass or unverified items are clearly recorded;
- no credential or private data appears in the diff;
- `/workspace` persistence assumptions remain valid;
- the user can reproduce the result from documented commands.
