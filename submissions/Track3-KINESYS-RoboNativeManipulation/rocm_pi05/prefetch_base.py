"""Prefetch pi05_base checkpoint from GCS anonymously into openpi's local cache.

Mirrors docs/amd_rocm_jax.md §2.1: train_jax.py's maybe_download() fails to use
an anon token for the openpi-assets bucket on hosts without GCP creds, so we
pre-populate the local cache so it returns instantly at train time.
"""
import fsspec, pathlib, os

src = "openpi-assets/checkpoints/pi05_base/params"
dst = pathlib.Path(os.path.expanduser("~/.cache/openpi/openpi-assets/checkpoints/pi05_base/params")).resolve()
dst.parent.mkdir(parents=True, exist_ok=True)

if (dst / "_METADATA").exists() or (dst / "manifest.ocdbt").exists():
    print("cache already present:", dst)
    raise SystemExit(0)

fs = fsspec.filesystem("gs", token="anon")
print("du bytes:", fs.du(src))
partial = dst.parent / "pi05_base_params.partial"
if partial.exists():
    import shutil
    shutil.rmtree(partial)
fs.get(src, str(partial), recursive=True)
partial.rename(dst)
print("DONE ->", dst)
# sanity: list expected artifacts
for name in ["_METADATA", "manifest.ocdbt", "_sharding", "d"]:
    p = dst / name
    print(f"  {'OK' if p.exists() else 'MISSING'}: {name}")
