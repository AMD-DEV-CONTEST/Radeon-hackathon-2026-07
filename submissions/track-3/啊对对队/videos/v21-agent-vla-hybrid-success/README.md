# v21 Agent + VLA Hybrid Videos

These three Genesis episodes use the same attribution boundary:

- Agent: high-level task conditioning only.
- v21 PI0.5: three-vote `side_suction` grasp-mode routing.
- Scripted controller: continuous pregrasp, contact, lift, transport, placement, and release.

They are hybrid simulation results, not pure-VLA or real-robot rollouts. Exact
distances, placement errors, requested/actual Agent model, and authority fields
are recorded in [`RESULTS.json`](RESULTS.json).

| Episode | Overview | Left wrist | Distance | Placement error |
| --- | --- | --- | ---: | ---: |
| 01 | [MP4](parcel-pi05-high-quality-bulk-v14-session-02-medium_carton-side_suction-candidate-05.mp4) | [MP4](parcel-pi05-high-quality-bulk-v14-session-02-medium_carton-side_suction-candidate-05-left-wrist.mp4) | 0.554 m | 24.2 mm |
| 02 | [MP4](parcel-pi05-high-quality-bulk-v14-session-00-medium_carton-side_suction-candidate-03.mp4) | [MP4](parcel-pi05-high-quality-bulk-v14-session-00-medium_carton-side_suction-candidate-03-left-wrist.mp4) | 0.546 m | 11.5 mm |
| 03 | [MP4](parcel-pi05-high-quality-bulk-v14-session-01-medium_carton-side_suction-candidate-08.mp4) | [MP4](parcel-pi05-high-quality-bulk-v14-session-01-medium_carton-side_suction-candidate-08-left-wrist.mp4) | 0.531 m | 25.0 mm |

Every delivered episode passed grasp, lift, transport, supported placement,
release, workspace, and force checks. The strict pure-VLA route remains 0/3.
