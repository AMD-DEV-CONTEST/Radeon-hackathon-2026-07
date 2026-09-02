"""Load a TOML run config and resolve paths relative to the repo root."""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Config keys that are filesystem paths and should be resolved to absolutes.
_PATH_KEYS = {
    ("teacher", "gguf"),
    ("teacher", "server_exe"),
    ("datagen", "seed_doc"),
    ("student", "hf_path"),
    ("export", "llama_src"),
    ("run", "out_root"),
    ("task", "spec"),
}


def load(path: str | Path) -> dict:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    for section, key in _PATH_KEYS:
        if section in cfg and key in cfg[section]:
            p = Path(cfg[section][key])
            if not p.is_absolute():
                p = REPO_ROOT / p
            cfg[section][key] = p
    return cfg
