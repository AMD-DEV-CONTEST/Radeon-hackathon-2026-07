# Windows Distribution

Xenix Radeon Edition is packaged locally for Windows 10/11 x64. This repository
does not own a GitHub Actions release workflow, remote artifact publication, or
an update-feed operating procedure.

## Build a verified bundle

Start from a clean source tree and use the repository-owned PDM commands:

```powershell
pdm install
pdm run check
pdm run test
pdm run package
pdm run smoke-package
```

`package` creates the PyInstaller `onedir` bundle under `dist/xenix`.
`smoke-package` starts the packaged application with an isolated runtime home and
exercises selected delayed native and data paths. Do not distribute a bundle
that fails either command.

## Choose a local distribution form

Create a ZIP archive:

```powershell
pdm run dist
```

Or create an unsigned per-user Velopack installer after the packaged smoke:

```powershell
dotnet tool restore
pdm run velopack
```

The Velopack toolchain is pinned by `.config/dotnet-tools.json` and
`release.toml`. Record the source commit, commands, package smoke result, output
checksum, and target Windows version with the distributed artifact.

## Security and rights

Treat every build-time provider secret, lock secret, and telemetry header as
extractable from a packaged desktop application. Use only credentials scoped for
redistribution or omit them. Distribution does not change the repository's
copyright, trademark, or third-party license obligations.

This repository intentionally contains no automated upload or public release
script. Selecting a hosting provider, signing installer artifacts, publishing an
update feed, or changing GitHub state requires a separately reviewed operation.
