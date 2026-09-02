"""Validate the public submission boundary and required artifacts."""

from __future__ import annotations

import json
import hashlib
import re
import sys
from pathlib import Path


FORBIDDEN = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"chengdu",
        r"\bxian\b",
        r"xi['’ -]?an",
        r"taipei",
        r"\bchina\b",
        "成都",
        "西安",
        "台北",
        "中国",
    )
]
SECRET_NAMES = (
    ".env",
    "rclone.conf",
    "id_rsa",
    "id_ed25519",
    "service_account",
    "service-account",
    "credential",
)
TEXT_SUFFIXES = {
    ".md", ".py", ".html", ".js", ".css", ".json", ".srt", ".txt",
    ".toml", ".yml", ".yaml", ".sh",
}
REQUIRED = (
    "README.md",
    "MANIFEST.json",
    "docs/QuakeSense_Project_Specification_EN.md",
    "docs/QuakeSense_AMD_Track2_Deck_EN.pptx",
    "demo/QuakeSense_Agentic_AI_AMD_Track2_Demo_EN.mp4",
    "demo/QuakeSense_Agentic_AI_AMD_Track2_Demo_EN.srt",
    "source/README.md",
    "source/requirements.txt",
    "public_demo/web/viewer.html",
)


def main(root: Path) -> int:
    failures: list[str] = []
    cities: set[str] = set()
    this_file = Path(__file__).resolve()
    for relative in REQUIRED:
        if not (root / relative).is_file():
            failures.append(f"missing required artifact: {relative}")

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        lowered = path.name.lower()
        if any(token in lowered for token in SECRET_NAMES):
            failures.append(f"secret-like filename: {path}")
        if path.resolve() == this_file:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text("utf-8-sig", errors="replace")
        if path.parent.name == "payloads" and path.suffix.lower() == ".json":
            payload = json.loads(text)
            cities.add(str(payload.get("title", "")))
            if "outline" in payload:
                failures.append(f"payload contains private outline: {path}")
            semantic = json.dumps(
                {key: value for key, value in payload.items() if key not in {"cells", "basemap", "layers"}},
                ensure_ascii=False,
            )
        else:
            semantic = text
        for pattern in FORBIDDEN:
            if pattern.search(semantic):
                failures.append(f"forbidden public term {pattern.pattern!r}: {path}")
        if re.search(r"[A-Za-z]:\\Users\\|/home/[^/]+/|/workspace/persistence/", semantic):
            failures.append(f"private absolute path: {path}")

    if len(cities) != 7:
        failures.append(f"expected 7 payload cities, found {len(cities)}: {sorted(cities)}")

    manifest_path = root / "MANIFEST.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text("utf-8-sig"))
        listed = {entry["path"]: entry for entry in manifest.get("files", [])}
        actual = {
            path.relative_to(root).as_posix(): path
            for path in root.rglob("*")
            if path.is_file()
            and path.name != "MANIFEST.json"
            and "__pycache__" not in path.parts
            and path.suffix.lower() != ".pyc"
            and ".pytest_cache" not in path.parts
        }
        for relative in sorted(actual.keys() - listed.keys()):
            failures.append(f"manifest missing file: {relative}")
        for relative in sorted(listed.keys() - actual.keys()):
            failures.append(f"manifest lists absent file: {relative}")
        for relative in sorted(actual.keys() & listed.keys()):
            path = actual[relative]
            entry = listed[relative]
            if path.stat().st_size != entry.get("bytes"):
                failures.append(f"manifest size mismatch: {relative}")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != entry.get("sha256"):
                failures.append(f"manifest hash mismatch: {relative}")
    if failures:
        print("\n".join(failures))
        return 1
    print("submission verified: required artifacts, 7 cities, no forbidden terms or secret-like files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".")))
