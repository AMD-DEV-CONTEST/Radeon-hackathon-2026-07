# Bring-up speed: the 30-min "get going" was serial HF downloads, not the code

One-liner: local start is 17s (measured Aug 5, pilot_4060, cold);
the "up to 30 minutes to get going" was Radeon session bring-up —
19GB of models re-downloaded single-stream and fully serialized on
every fresh instance. up.sh now parallelizes and caches; verify the
claimed numbers on the next paid session before repeating them.

What changed (Aug 5, all logic dry-run-tested in WSL, three scenarios:
fresh / rebuilt-with-cache / broken-downloader):

- scripts/up.sh: pip deps + teacher download + student download run in
  parallel; hf_transfer installed and HF_HUB_ENABLE_HF_TRANSFER=1 (plus
  HF_XET_HIGH_PERFORMANCE=1) with automatic retry without the flag if
  the accelerated path fails; models download into
  /workspace/foundry-models with models/teacher and models/student/*
  as symlinks, so IF /workspace persists across instance rebuilds, the
  next session's downloads are skip-if-present no-ops.
- foundry/teacher.py: llama-server health deadline 180s -> 420s (30B
  load observed ~2 min; 180 left no margin, and a cache volume could be
  slower on first read).
- SHOOT_DAY.md BLOCK 1 and RADEON_RUNBOOK Session 1.5 now go through
  scripts/up.sh. foundry-transfer.tar.gz rebuilt with the new files
  (rebuild recipe: extract old tarball, overlay changed files, re-tar —
  never tar runs/ from the repo, it is 16GB; the tarball's runs/ is a
  hand-curated 400KB).

VERIFIED on the instance (Aug 5 session, new image — see the
radeon-cloud-instance note for the image change):
- READY in 446s (~7.5 min) on a worst-case bare image: llama.cpp built
  from source (~6-7 min, the long pole) AND 18GB teacher downloaded,
  overlapped. Accelerated download is dramatically faster than the old
  single-stream: progress log showed ~8GB in one 15s window.
- pip install hf_transfer works on the image.
- up.sh reordered afterward so downloads start BEFORE a source build
  (the overlap this session needed a manual pre-download cell for is
  now automatic); re-verified in the WSL sandbox.

Still open:
- /workspace persistence across destroy/recreate: the Aug 5 instance
  came up empty, but it was also a different image, so template
  migration may explain it. Until a same-template rebuild shows files
  surviving, assume the cache only helps within one instance lifetime.
