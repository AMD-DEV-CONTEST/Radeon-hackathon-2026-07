# AetherDB V1.31.2 Deployment

The primary end-user distribution is the Tauri desktop application. It builds
native graphical installers on Windows, macOS and Linux and starts its own
dynamic loopback sidecar.

## Docker Core

Docker Core is a local browser/server profile. It does not contain API keys,
user databases, logs, backups, Ollama, model weights or local configuration.

```bash
cp deploy/docker/.env.example deploy/docker/.env
docker compose \
  --env-file deploy/docker/.env \
  -f deploy/docker/docker-compose.yaml \
  up --build -d
docker compose \
  --env-file deploy/docker/.env \
  -f deploy/docker/docker-compose.yaml \
  port aetherdb-core 8765
```

The host port defaults to an automatically allocated loopback port. The
container creates `config.local.yaml` and `.api_keys.json` inside the private
`aetherdb-runtime` volume on first start. Inspect them only from the local
container when configuring a client; do not copy them into the repository.

Core constraints:

- one Web worker for SQLite;
- non-root, read-only application filesystem;
- writable runtime and model volumes only;
- no fixed port 8000;
- no tracked `config.yaml`;
- no bundled model weights or Ollama runtime.

The competition ROCm profile is separate from Core:

- `deploy/docker/Dockerfile.rocm`
- `deploy/docker/docker-compose.competition.yaml`
- `deploy/COMPETITION_REPRODUCTION.md`
- `deploy/ROCM_MODEL_COMPATIBILITY.md`

It requires an immutable final image digest, Linux ROCm devices, a real
framework calculation and independent per-model Worker evidence. A Docker file
existing in the repository is not proof of a successful Linux, ROCm or model
run.

## Local Service Validation Files

`deploy/linux/` and `deploy/windows/` are loopback-only service helpers for
advanced operators. They are not graphical installers and do not enable
`hosted_bridge` or `full_server_deployment`.

The helpers enforce:

- an available explicit loopback port, never fixed port 8000;
- one application process for SQLite;
- separate read-only resources and private writable runtime data;
- generated local credentials that are never printed or embedded in a unit;
- 120-second readiness and 30-second shutdown boundaries;
- no public firewall rule, nginx listener, or automatic tool download.

The Windows helper requires an independently installed and verified NSSM
executable. The Linux helper installs an `aetherdb-local` systemd unit and
leaves the nginx reservation disabled.

For a graphical independent window, use the host-native Tauri packages:
Windows NSIS, macOS app/DMG, or Linux DEB/AppImage. Native acceptance must run
on each target operating system.
