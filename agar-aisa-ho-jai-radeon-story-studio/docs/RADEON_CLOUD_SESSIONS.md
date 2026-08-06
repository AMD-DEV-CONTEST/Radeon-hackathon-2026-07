# Radeon Cloud session notes

This public snapshot includes the source needed to package and verify a Radeon Story Studio run. The original private SSH/session files are intentionally excluded.

Use a local session JSON that you create on your own machine and keep it outside the public repository, for example:

```text
local/radeon-cloud/session.json
```

A session JSON should contain only the current Radeon Cloud host, user, key path, and workspace details needed by your own environment. Do not commit it.

Typical validation flow:

```bash
python3 tools/episode_factory/manage_radeon_cloud_session.py probe-ssh \
  local/radeon-cloud/session.json

python3 tools/episode_factory/manage_radeon_cloud_session.py run-remote \
  local/radeon-cloud/session.json \
  /tmp/aahj-amd-devmaster-demo/execution-package.tar.gz \
  --destination /tmp/aahj-amd-devmaster-demo/result

python3 tools/episode_factory/manage_amd_story_studio.py verify-result \
  /tmp/aahj-amd-devmaster-demo/result/result.json \
  --result-root /tmp/aahj-amd-devmaster-demo/result
```

The remote runner fails closed unless ROCm-enabled PyTorch is available, HIP is reported, an AMD Radeon device is visible, and a real tensor operation succeeds.
