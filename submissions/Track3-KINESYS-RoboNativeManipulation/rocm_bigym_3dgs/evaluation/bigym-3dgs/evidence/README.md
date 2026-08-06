# Published evaluation evidence

This directory is reserved for accepted formal policy-evaluation receipts.
Smoke runs, interrupted attempts and task-failed trajectories are diagnostic
artifacts and must remain under the local `RESULTS_ROOT`; they must not be
committed as release evidence.

A publishable JSON receipt must declare:

- `publication_status: accepted_formal_evaluation`;
- `benchmark.mode: formal` and a positive `benchmark.n_episodes`;
- `gates.recording_validation: true`;
- `gates.result_validation: true`;
- `gates.human_three_camera_review: true`.

`scripts/verify_public_repo.sh` enforces this contract for every tracked JSON
file in this directory. This revision contains no accepted formal policy
evaluation receipt.
