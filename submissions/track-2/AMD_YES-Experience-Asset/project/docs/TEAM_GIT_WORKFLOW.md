# Three-Person Git and Persistent-Workspace Workflow

> **Final-sprint execution amendment (2026-08-05):** for the remaining E5–E9
> work, follow [`spec/FINAL_SPRINT_EXECUTION_PACKAGE.md`](../spec/FINAL_SPRINT_EXECUTION_PACKAGE.md).
> Kali owns one E5–E8 Baseline integration lane, the owner owns Stage 1/Stage 2,
> and Ethan owns E9. Developers do not wait for stage-by-stage human approval;
> PRs remain branch, CI, evidence, handoff, rollback, and merge boundaries.
> Private blind evaluation is not a remaining gate. Main-branch, secret,
> force-push, persistence, and evidence safeguards below still apply.

Last updated: 2026-07-24

## The two sources of truth

`/workspace` and Git solve different problems:

```text
/workspace Persistent PVC
  -> fast working copy, model cache, venvs, logs, benchmarks, local data

GitHub repository
  -> durable source-code history, team review, rollback, handoff, final submission
```

The organizer message that only `/workspace` persists is operationally
important, but persistence is not backup. A PVC can still be deleted,
misconfigured, corrupted, or tied to one account. Source code is not considered
safe until it is committed and pushed to the team repository.

The live instance measured `/workspace` as a 97.9 GiB ext4 PVC. After the
coding-agent environments and smoke model were installed, about 79–80 GiB
remained free. Capacity does not change the backup rule.

## Recommended team shape

Use one policy-protected `main` branch and one short-lived branch per task:

```text
main
├── feat/jy-agent-runtime
├── feat/member2-rag
└── feat/member3-evaluation
```

Recommended ownership:

- Member 1 / integration and quality owner: milestone/PR gate, private blind
  evaluation, canonical benchmark coordination, submission and demo sign-off.
- Member 2 / Lane A: domain/API, persistence, Agent runtime and policy, local
  inference adapter, W7900/ROCm/vLLM evidence.
- Member 3 / Lane B: React UI, typed API client, renderers, browser/E2E evidence,
  English-facing demo and presentation assets.

The official operational limit is one single-GPU pod **per account**, not one
pod for the whole team. Team members may therefore use separate pods only when
their own registration, account approval, credits, and instance access are
confirmed. Do not make a delivery dependency assume that all three pods exist.

Designate one canonical W7900 integration profile for acceptance and contest
numbers even when several development pods are available. Other pods can run
component checks in parallel, but their results are comparable only when the
hardware/software/model/workload manifests match. A teammate without an active
pod can still work locally against typed mocks and merge through review.

### Current `main`-branch enforcement gap

The repository is private under a personal GitHub account, and the current
plan does not expose GitHub branch-protection/ruleset enforcement. Collaborators
with `write` access can technically push to `main`, even though the team policy
forbids it. Until technical protection becomes available, use this fallback:

- only the integration/quality owner merges approved Pull Requests;
- collaborators and coding Agents push task branches only;
- no one merges their own implementation PR;
- every PR passes required checks and records its Issue/evidence mapping;
- before a merge, the owner records the current `main` commit as the rollback
  point and confirms that the branch is pushed to GitHub;
- an accidental direct push is treated as an incident: stop integration,
  preserve the commit, review the diff and checks, then revert through a new
  reviewed commit if required; never rewrite shared history.

This is governance, not a technical lock. If branch protection later becomes
available, enable required PR review and required status checks without
changing the review policy above.

## Daily branch workflow

```bash
git switch main
git pull --ff-only
git switch -c feat/<member>-<topic>

# Work and test.
git status --short
git diff
git add -p
git commit -m "feat(scope): concise result"
git push -u origin HEAD
```

Before resuming a branch:

```bash
git fetch origin
git rebase origin/main
```

Resolve conflicts on the task branch, rerun tests, and push normally. Do not
force-push shared branches. Keep commits small enough to review and revert.

## When several people must use the same pod

Never edit the same checkout concurrently. Create a separate worktree for each
person:

```bash
cd /workspace/amd-track2-agent/repo
mkdir -p /workspace/amd-track2-agent/worktrees

git fetch origin
git worktree add \
  /workspace/amd-track2-agent/worktrees/<member> \
  -b feat/<member>-<topic> origin/main
```

All worktrees still share one Unix account and one trust boundary. They isolate
files and branches, not credentials or GPU resources. Coordinate GPU-heavy
tests and do not run multiple model servers without agreeing on ports and VRAM.

## Credentials

- Never copy a developer's SSH private key into Radeon Cloud.
- Never commit GitHub, Hugging Face, OpenAI, or Anthropic tokens.
- Because the pod uses one shared Unix account, do not persist three personal
  GitHub credential stores there.
- Prefer a designated integrator for pushes from the pod. Other members push
  their branches from their own machines.
- If a teammate must push from the pod, use a short-lived, least-privilege
  credential for that session and remove it afterward. Do not place it in
  `.env`, shell profiles, Git remotes, or `/workspace`.

Codex and Claude Code authentication files stay under the user's home directory
and are intentionally excluded from the persistent project. They may need
sign-in again after a pod rebuild.

## Commit and push checkpoints

Commit after a coherent, tested change. Push:

- after every validated checkpoint;
- before another teammate takes over;
- before risky dependency or model-runtime experiments;
- before stopping or destroying the Radeon Cloud instance;
- before a performance test or process that might crash the pod;
- at least once at the end of every work session.

Coding agents may edit, test, and create small local commits on an assigned task
branch when the task explicitly allows it. A checkpoint push is allowed only
after the agent records the tests, inspects the diff, confirms that no secret or
large artifact is included, and reports the commit SHA. Agents never push
directly to `main`, merge their own pull request, force-push a shared branch, or
change repository visibility.

For this three-person team, use the following default:

```text
developer/coding agent -> feat/<member>-<topic> -> push checkpoint
reviewer or GPU integrator -> review + GPU evidence -> merge to main
```

Every PR must also follow the active public quality contract in
`docs/team-alignment/TEAM_QUALITY_CONTRACT.md`: map the change to its `AC-*`,
L1 milestone and L2 capability gate, and attach only public/non-sensitive
evidence. Private blind tests, gold outputs, exact scoring and quality-owner-only
materials remain outside the shared repository and teammate Agent context.

This preserves the token-saving benefit of coding agents without turning every
file edit into a manual approval, while retaining review at the branch and
publication boundary.

## Pre-stop gate

Before ending a cloud session:

```bash
cd /workspace/amd-track2-agent/repo
bash scripts/pre_stop_checkpoint.sh
```

The script fails when there are uncommitted changes, the branch has no upstream,
or local commits have not been pushed. It never commits or pushes by itself.

Large artifacts such as model weights, caches, private datasets, and raw traces
do not belong in Git. Preserve only the minimal reproducible configuration and
approved benchmark summaries.
