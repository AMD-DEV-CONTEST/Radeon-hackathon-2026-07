# Competition resources and rule decisions

This file records the references reviewed through 2026-07-27. The machine-readable
snapshot is `configs/competition-resources-v1.json`.

## Authority

Use the sources in this order when wording differs:

1. [ModelScope official event rules](https://modelscope.cn/events/299)
2. [Official GitHub submission repository](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)
3. Training-camp Feishu guides and FAQ

The official event page sets the final deadline to **2026-08-06 23:59
Beijing time**. Its Track 3 overview says environment execution, model training,
and real-time inference must be completed on a **single AMD Radeon GPU**. The
project therefore treats a single-GPU Radeon Cloud training and inference path
as a hard promotion gate, even though the detailed scoring text also describes
training and/or inference as key ROCm stages.

## References

- [Training materials](https://xcnm8tq2cqpm.feishu.cn/wiki/O5CrwNhHRiQBC2kv46xclCBynPd?from=from_copylink)
- [Submission guide](https://xcnm8tq2cqpm.feishu.cn/wiki/FjxHwO03CiM0dBkwOfUcA1tNnNf?from=from_copylink)
- [Dynamic FAQ](https://xcnm8tq2cqpm.feishu.cn/wiki/D9jVwO1xhimZIKklyAqcy6wEnIf?from=from_copylink)
- [Official event](https://modelscope.cn/events/299)
- [AMD Developer Program China](https://developer.amd.com.cn/login?source=PmqEYQZa1)
- [Official submission repository](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)
- [Radeon Cloud access guide](https://my.feishu.cn/wiki/WZjewQhHBi5qvwk0U1Sca8Qenfg?from=from_copylink)

## Resolved submission choices

- Submit by forking the official repository and opening a Pull Request titled
  `Track 3, <team name>, <application name>`.
- The official repository says all submission materials, descriptions, and PRs
  must be in English. The training-camp guide asks for a bilingual README. We
  satisfy both with English-primary material and a Chinese mirror.
- The official video recommendation is 3–5 minutes while the training-camp
  guide recommends no more than 3 minutes. Target an approximately **3:00**
  subtitled video.
- Keep the fork public, include a project license and dependency specification,
  never commit secrets, and do not upload files over 100 MB directly.
- Do not upload datasets. Provide deterministic generation/download
  instructions and immutable dataset receipts instead.
- Preserve a screenshot of the accepted PR before the deadline.

## Radeon Cloud operational boundary

Use only `https://radeon-global.anruicloud.com/`. The training guidance
recommended the `proxy` template, but that Gallery entry was absent when the
verified instance was created; the actual run used the available Blank
OpenCode Workspace template. Select PVC storage and keep the environment,
code, caches, datasets, checkpoints, and receipts below `/workspace`; Local
Storage was not treated as persistent in that historical snapshot.

On 2026-07-29 the participant supplied an organizer broadcast naming
`/workspace/persistence`. A recreated official workspace proved that path
absent and exposed `/workspace/persistent -> /persistent` on a 100 GiB NFS
PVC. The participant explicitly adopted the observed path, and one minimal
write/read/delete canary passed. Future work therefore uses
`configs/amd-persistence-layout-v2.json`; direct `/workspace/*` siblings other
than the adopted `persistent` link are ephemeral. Historical receipts and the
superseded notice-path contracts retain their exact old paths.

The official single-GPU instance has since completed verified environment,
ACT training, open-loop inference, and exact-seed G3 execution. Its identity
and the template divergence are recorded in
`configs/amd-cloud-runtime-v1.json`; this dated execution history does not
guarantee future capacity or availability.

On 2026-07-27 the public GitHub repository still exposed the English-only,
fork-and-PR, PR-title, and Track 3 deliverable requirements. The ModelScope
page was reachable but its dynamic rule body was not exposed to the read-only
fetch, and the Feishu pages were not machine-readable. The guides are dynamic:
re-check the official event page, official repository, submission guide, and
FAQ before the final packaging freeze.
