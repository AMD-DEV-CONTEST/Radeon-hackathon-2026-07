"""Download lightweight Screen-AI model artifacts into the project.

Usage:
    python ai_pc_operator/backend/scripts/download_models.py
    python ai_pc_operator/backend/scripts/download_models.py --skip-llm
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[1]
MODEL_DIR = ROOT / "ai_pc_operator" / "data" / "models"
MANIFEST = MODEL_DIR / "models_manifest.json"


@dataclass(frozen=True)
class DownloadSpec:
    name: str
    repo: str
    filename: str
    target: str
    role: str
    active: bool
    min_size_mb: int = 1

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/main/{self.filename}"


SPECS = [
    DownloadSpec(
        name="qwen-1.5b-q4",
        repo="Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
        filename="qwen2.5-coder-1.5b-instruct-q4_0.gguf",
        target="qwen2.5-coder-1.5b-instruct-q4_0.gguf",
        role="local planner LLM through llama.cpp",
        active=True,
        min_size_mb=900,
    ),
    DownloadSpec(
        name="ocr-mobile-detector",
        repo="monkt/paddleocr-onnx",
        filename="detection/v3/det.onnx",
        target="ocr_det_v3.onnx",
        role="light ONNX text region detector",
        active=True,
        min_size_mb=2,
    ),
    DownloadSpec(
        name="ocr-mobile-recognizer",
        repo="monkt/paddleocr-onnx",
        filename="languages/english/rec.onnx",
        target="ocr_rec_english.onnx",
        role="light ONNX English text recognizer",
        active=True,
        min_size_mb=7,
    ),
    DownloadSpec(
        name="omniparser-v2-icon-detector-teacher",
        repo="microsoft/OmniParser-v2.0",
        filename="icon_detect/model.pt",
        target="teachers/omniparser_v2_icon_detect.pt",
        role="teacher/cloud detector for later INT8 ONNX distillation",
        active=False,
        min_size_mb=35,
    ),
    DownloadSpec(
        name="omniparser-v2-icon-detector-config",
        repo="microsoft/OmniParser-v2.0",
        filename="icon_detect/model.yaml",
        target="teachers/omniparser_v2_icon_detect.yaml",
        role="teacher detector config",
        active=False,
        min_size_mb=0,
    ),
]


def download(spec: DownloadSpec, force: bool) -> dict:
    target = MODEL_DIR / spec.target
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and target.stat().st_size >= spec.min_size_mb * 1024 * 1024 and not force:
        print(f"[skip] {spec.name}: {target.name} already present")
        return record(spec, target, "present")

    temp = target.with_suffix(target.suffix + ".part")
    resume_at = temp.stat().st_size if temp.exists() else 0
    headers = {"User-Agent": "Screen-AI-model-downloader/1.0"}
    if resume_at:
        headers["Range"] = f"bytes={resume_at}-"

    print(f"[download] {spec.name} -> {target}")
    req = urllib.request.Request(spec.url, headers=headers)
    started = time.time()
    mode = "ab" if resume_at else "wb"
    try:
        with urllib.request.urlopen(req, timeout=60) as response, temp.open(mode) as handle:
            total = response.headers.get("content-length")
            total_bytes = int(total) + resume_at if total and resume_at else int(total or 0)
            done = resume_at
            last_print = 0.0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last_print > 2:
                    if total_bytes:
                        pct = done / total_bytes * 100
                        print(f"  {done / 1024**2:.1f}/{total_bytes / 1024**2:.1f} MB ({pct:.1f}%)")
                    else:
                        print(f"  {done / 1024**2:.1f} MB")
                    last_print = now
    except Exception:
        print(f"[partial] kept resume file: {temp}")
        raise

    temp.replace(target)
    elapsed = max(time.time() - started, 0.001)
    print(f"[ok] {target.name}: {target.stat().st_size / 1024**2:.1f} MB in {elapsed:.1f}s")
    return record(spec, target, "downloaded")


def record(spec: DownloadSpec, target: Path, status: str) -> dict:
    payload = asdict(spec)
    payload.update(
        {
            "status": status,
            "path": str(target),
            "size_mb": round(target.stat().st_size / (1024**2), 2) if target.exists() else 0,
            "source_url": spec.url,
        }
    )
    return payload


def write_manifest(records: list[dict]) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "model_dir": str(MODEL_DIR),
        "records": records,
        "notes": [
            "Active runtime models are small CPU-loadable artifacts.",
            "OmniParser V2 is stored as a teacher artifact for cloud distillation, not loaded on 4 GB laptops.",
            "The trained/exported ui_detector_int8.onnx should be copied here when the cloud distillation run finishes.",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[manifest] {MANIFEST}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="redownload existing files")
    parser.add_argument("--skip-llm", action="store_true", help="skip the large GGUF planner model")
    parser.add_argument("--active-only", action="store_true", help="skip teacher/cloud artifacts")
    args = parser.parse_args()

    selected = SPECS
    if args.skip_llm:
        selected = [spec for spec in selected if not spec.target.endswith(".gguf")]
    if args.active_only:
        selected = [spec for spec in selected if spec.active]

    records = [download(spec, args.force) for spec in selected]
    write_manifest(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
