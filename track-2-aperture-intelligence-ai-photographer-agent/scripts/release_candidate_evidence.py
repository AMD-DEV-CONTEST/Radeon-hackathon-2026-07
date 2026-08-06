"""Run repeatable release-candidate evidence requests against the local web API."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import time
import urllib.error
import urllib.request
from pathlib import Path
from statistics import mean
from typing import Any


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _post(url: str, image: Path, timeout: int) -> tuple[dict[str, Any], float]:
    payload = json.dumps(
        {"filename": image.name, "image": _data_url(image)},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    return result, time.perf_counter() - started


def _deep_get(value: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def _summary(case: str, run: int, result: dict[str, Any], wall_seconds: float) -> dict[str, Any]:
    analysis = result.get("analysis") or result.get("vision_analysis") or {}
    people = analysis.get("people_boxes") or result.get("people_boxes") or []
    props = analysis.get("visible_props") or analysis.get("props") or []
    plan = (
        result.get("shooting_plan")
        or result.get("plan")
        or result.get("photography_plan")
        or {}
    )
    subject = plan.get("subject_instruction") or {}
    metrics = result.get("metrics") or {}
    critic = result.get("critic") or {}
    return {
        "case": case,
        "run": run,
        "http_wall_seconds": round(wall_seconds, 3),
        "inference_seconds": metrics.get("inference_seconds"),
        "total_seconds": metrics.get("total_agent_seconds") or metrics.get("total_seconds"),
        "peak_allocated_vram_gib": metrics.get("peak_allocated_vram_gib"),
        "vision_attempts": metrics.get("vision_attempts"),
        "people_count": len(people),
        "visible_props": props,
        "photo_intent": plan.get("photo_intent"),
        "hand_action": subject.get("hand_action"),
        "critic_status": critic.get("status"),
        "critic_passed": critic.get("passed"),
        "card_filename": _deep_get(result, "pose_card", "filename"),
        "orientation": _deep_get(result, "image", "orientation"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:7860/api/analyze")
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Reuse completed JSON/PNG pairs and continue an interrupted run.",
    )
    args = parser.parse_args()

    cases = [
        ("01_single_with_phone", args.samples / "01_single_with_phone.jpg"),
        ("02_single_no_prop", args.samples / "02_single_no_prop.jpg"),
        ("03_group_three_people", args.samples / "03_group_three_people.jpg"),
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []

    # Case-major ordering gives each scenario one first/cold-ish run and two warm runs.
    for case, image in cases:
        case_dir = args.output / case
        case_dir.mkdir(parents=True, exist_ok=True)
        for run in range(1, args.runs + 1):
            stem = f"run_{run:02d}"
            json_path = case_dir / f"{stem}.json"
            png_path = case_dir / f"{stem}.png"
            if args.skip_existing and json_path.is_file() and png_path.is_file():
                result = json.loads(json_path.read_text(encoding="utf-8"))
                item = _summary(case, run, result, 0.0)
                item["reused_existing_evidence"] = True
                summaries.append(item)
                print(f"[evidence] reuse {case} run {run}/{args.runs}", flush=True)
                continue
            print(f"[evidence] {case} run {run}/{args.runs}", flush=True)
            result, wall_seconds = _post(args.url, image, args.timeout)
            card = result.get("pose_card") or {}
            card_data_url = card.pop("data_url", "")
            if not card_data_url.startswith("data:image/png;base64,"):
                raise RuntimeError(f"{case} run {run}: response did not contain a PNG card")
            png_bytes = base64.b64decode(card_data_url.split(",", 1)[1])
            png_path.write_bytes(png_bytes)
            json_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            item = _summary(case, run, result, wall_seconds)
            summaries.append(item)
            print(json.dumps(item, ensure_ascii=False), flush=True)

    successful = [item for item in summaries if item.get("critic_status") != "failed"]
    wall_values = [float(item["http_wall_seconds"]) for item in summaries]
    report = {
        "runs_requested": len(cases) * args.runs,
        "runs_completed": len(summaries),
        "critic_non_failed_runs": len(successful),
        "mean_http_wall_seconds": round(mean(wall_values), 3),
        "min_http_wall_seconds": min(wall_values),
        "max_http_wall_seconds": max(wall_values),
        "runs": summaries,
    }
    (args.output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("[evidence] complete", flush=True)


if __name__ == "__main__":
    main()
