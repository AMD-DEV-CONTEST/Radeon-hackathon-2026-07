#!/usr/bin/env python3
"""Fetch reBotArm_control_py source from GitHub (no git clone, skips STL meshes).

Use when git/curl to github.com fails with TLS errors but raw.githubusercontent.com works.
Incremental: skips files that already exist unless --force.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "vectorBH6/reBotArm_control_py"
BRANCH = "main"
BASE_RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
TREE_API = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"

SKIP_SUFFIXES = (".STL", ".stl", ".lock")
SKIP_PREFIXES = ("example/", "urdf/", ".vscode/")


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "botversex-sdk-fetch"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _should_fetch(path: str) -> bool:
    if any(path.endswith(s) for s in SKIP_SUFFIXES):
        return False
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return False
    if path == "uv.lock":
        return False
    return True


def _patch_pyproject(dest: Path) -> None:
    pyproject = dest / "pyproject.toml"
    if not pyproject.is_file():
        return
    text = pyproject.read_text(encoding="utf-8")
    text = text.replace('requires-python = ">=3.10,<3.12"', 'requires-python = ">=3.10,<3.13"')
    if "[build-system]" not in text:
        text = text.rstrip() + """

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["reBotArm_control_py*"]
"""
    if "matplotlib" in text:
        text = "\n".join(
            line for line in text.splitlines() if "matplotlib" not in line
        ) + "\n"
    pyproject.write_text(text, encoding="utf-8")


def _patch_config(dest: Path) -> None:
    rs_cfg = dest / "config" / "rebotarm_rs.yaml"
    bv_urdf = dest.parents[1] / "apps" / "realtime" / "static" / "urdf" / "b601_rs" / "b601_rs.urdf"
    if rs_cfg.is_file() and bv_urdf.is_file():
        lines = []
        for line in rs_cfg.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("urdf_path:"):
                lines.append(f'urdf_path: "{bv_urdf.resolve()}"')
            else:
                lines.append(line)
        rs_cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")

    global_cfg = dest / "config" / "rebotarm.yaml"
    if global_cfg.is_file():
        global_cfg.write_text(
            '# reBotArm global config\nhardware_yaml: "rebotarm_rs.yaml"\n',
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-download all files")
    args = parser.parse_args()

    dest = Path(__file__).resolve().parents[1] / "vendor" / "reBotArm_control_py"
    dest.mkdir(parents=True, exist_ok=True)

    print(f"[b601-sdk-fetch] listing tree from {TREE_API}")
    tree = json.loads(_fetch(TREE_API).decode())
    paths = sorted(
        item["path"]
        for item in tree.get("tree", [])
        if item.get("type") == "blob" and _should_fetch(item["path"])
    )
    todo = [p for p in paths if args.force or not (dest / p).is_file()]
    print(f"[b601-sdk-fetch] {len(todo)}/{len(paths)} files to download")

    ok, fail, skipped = 0, 0, len(paths) - len(todo)
    for rel in todo:
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        url = f"{BASE_RAW}/{rel}"
        try:
            out.write_bytes(_fetch(url))
            ok += 1
            print(f"  OK {rel}")
        except urllib.error.URLError as exc:
            fail += 1
            print(f"  FAIL {rel}: {exc}", file=sys.stderr)

    _patch_pyproject(dest)
    _patch_config(dest)

    print(f"[b601-sdk-fetch] done: {ok} ok, {fail} failed, {skipped} skipped -> {dest}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
