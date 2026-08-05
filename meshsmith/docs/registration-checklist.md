# Your to-do list (only you can do these — accounts & identity)

Deadline: **Wed Aug 6, 11:59 PM Beijing time = Wed Aug 6, 11:59 AM US Eastern.**

## 1. Register (≈10 min, do these first)
- [x] **AMD AI Developer Program** — confirmed: Bradley Grubbs / bgrubbs@vt.edu ✓
- [x] **Luma EVENT registration** — form completed 2026-08-05 with:
      Team Name `N/A` (solo) · Track 1: Multimodal AI Creation ·
      GitHub `bgrubbs1` · Discord `brad84_73555` · AMD email `bgrubbs@vt.edu` ·
      both consent boxes ticked. Confirm the submission went through.
- [x] **Discord** — ID `brad84_73555` (join https://discord.gg/zt9caur5B3 if not already in)
- [x] GitHub ID: bgrubbs1 ✓

**PR title, locked:** `Track 1, Bradley Grubbs, MeshSmith`
(Team Name was `N/A`, so the organizers' rule applies: use your own name.)

> The Luma form notes that the AMD-registered email is how they **issue Radeon Cloud
> credits**. So this registration is what unlocks the GPU access needed for the demo
> video — watch bgrubbs@vt.edu for it.

## 2. Radeon Cloud GPU (≈10 min, then Claude takes over)
- [ ] Log in at https://radeon-global.anruicloud.com/ (Login with Email — use the same
      email as the AMD Developer Program)
- [ ] Profile → paste an SSH **public** key (e.g. `type $env:USERPROFILE\.ssh\id_ed25519.pub`;
      generate with `ssh-keygen -t ed25519` if missing)
- [ ] Profile → Add Template: any **rocm/pytorch** container image, Storage = Persistent
      (PVC), **SSH Access = ON** → Launch
- [ ] Paste the shown SSH command/host/port into the chat — from there Claude can install
      MeshSmith on the Radeon box, run the ROCm benchmark, and stage the demo
      (`bash scripts/radeon_cloud_setup.sh` does the whole setup in one command)
- [ ] Remember: **Destroy Instance** when finished — running instances consume credits

## 3. Final submission (Claude prepares; you approve)
- [ ] Demo video 3–5 min showing the app on the Radeon GPU (script: `docs/demo-script.md`).
      **This is a required deliverable and must show AMD hardware** — the only footage
      that exists was shot on the NVIDIA box and is deliberately gitignored.
      Note the minimum: the rehearsal recording ran 2:07, under the 3-minute floor.
- [ ] Approve: fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` + PR titled
      `Track 1, Bradley Grubbs, MeshSmith` (body ready in `docs/pr-body.md`)

## Official answers from #devmaster-faq (Uncy_AMD, AMD staff)
- **Demo video is MANDATORY.** No way around it.
- **Video may be a LINK** — "Bilibili, YouTube, or cloud drive links are all accepted
  as long as the link opens and can be played." So it need not be committed to the
  repo; a URL in the PR body is fine (and keeps the repo small).
- **Credits are issued off your Luma registration email** — the Radeon Cloud login
  email must match the Luma one. (Ours match: bgrubbs@vt.edu both sides.)
- **Radeon Cloud instance settings:** Image = `GH-proxy-stable` (recommended, works
  out of the box); Storage = `Persistent (PVC)`.
- **Platform stress tests kill all running instances** — a heads-up is posted in the
  channel first. Don't leave an unfinished recording session running.
- Support: AMD engineers answer directly in the DevMaster channels.

⚠️ **Deadline discrepancy:** the Discord event card says "Ends Thu Aug 6th · 9:00 PM",
but the Luma confirmation email and the rules doc both say **Aug 6, 11:59 AM EDT**.
Treat 11:59 AM EDT as the deadline — it is the earlier and officially documented one.

## Already verified (no action needed)
- Clean-room install proven: `docker/Dockerfile.deptest` builds from a bare
  `python:3.12-slim` and passes the smoke test — so the dependency list is complete.
- Two install-blockers found and fixed that only appear on a clean machine:
  Hunyuan3D's undeclared `torchvision` dep, and `libGL.so.1` missing on slim images.
