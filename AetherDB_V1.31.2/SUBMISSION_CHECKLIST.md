# AetherDB V1.31.2 Official Submission Checklist

## Required manual information

- [x] Participant name in `PR_DESCRIPTION.md`: 陈sir.
- [x] PR title: `Track 1, 陈sir, AetherDB`.
- [x] Participant name matches the Luma registration; this is a solo-developed project.
- [x] Project license: GNU Affero General Public License v3.0 only (`AGPL-3.0-only`).

## Materials

- [x] Bilingual Project Profile PDF.
- [x] 3-5 minute demo video (4:20.854, 1920x1080, 88.86 MiB).
- [x] Bilingual one-page poster.
- [x] English primary README with complete environment, startup, dependency, architecture, model, and ROCm information.
- [x] Chinese README counterpart.
- [x] English PR description.
- [x] Complete sanitized source tree generated and independently verified (428 files, manifest hashes match).

## Privacy and repository hygiene

- [x] No `.api_keys.json`, `config.local.yaml`, `config.yaml`, `.env`, database, logs, user content, or local runtime state.
- [x] No Cold X, DeepSeek, OpenAI, or other private API credentials.
- [x] No model weights, generated sidecar binaries, `node_modules`, `dist`, `target`, caches, or internal agent directories.
- [x] No `backend-startup-*.json` temporary descriptors.
- [x] No `markdown文件存放区`, `local_agent_runs`, internal handoff records, or obsolete roadmaps.
- [x] `deploy/docker/.env.competition.example` is present and contains placeholders only.

## Verification

- [x] `python -m compileall main.py api app services routes tests`
- [x] `python check_routes_auth.py` (0 failures, 0 real issues).
- [x] `python -m pytest` (374 passed).
- [x] `cd frontend && pnpm run test:api` (34 passed).
- [x] `cd frontend && pnpm run build`.
- [x] Sanitized source secret scan passes.
- [x] Fresh-copy runtime initialization succeeds; generated private runtime files were removed from the submission copy after verification.
- [x] Correct Project Profile PDF contains V1.31.2 and does not contain AetherDB 2.0.
- [x] Video metadata confirms 4:20.854, 1920x1080, 60 fps, and stereo 44.1 kHz audio.
- [ ] Manually play the submitted video from beginning to end after the final Git checkout.
- [ ] ROCm claims in the submission match evidence collected on the actual AMD Linux host.

## 中文提醒

- 正式 PR 标题和正文必须使用英文，双语材料中的英文内容必须完整。
- 提交前填写团队名或报名者姓名，不要使用临时占位符。
- 源码包只能包含可运行和可复现所需内容，不提交内部 Markdown、密钥、用户数据、日志或模型权重。
- 视频 88.86 MiB，低于 GitHub 100 MiB 单文件硬限制，但超过 50 MiB 警告阈值；推送前确认官方仓库是否接受直接提交，必要时改用稳定公开链接。
