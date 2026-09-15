#!/usr/bin/env python3
"""Import a combined transcription JSON into the Find it DB.

The JSON must contain:
  {
    "frame_descriptions": [{"timestamp": float, "description": str}, ...],
    "transcriptions": [{"index": int, "start_seconds": float,
                        "end_seconds": float, "text": str}, ...]
  }

The import process is:
  1. Clear all existing frame/audio transcriptions for the video id.
  2. Parse the supplied JSON file.
  3. Insert the new rows into the database.

Usage:
    python import_transcriptions.py <video_id> --json combined.json
    python import_transcriptions.py <video_id> --json combined.json --base-url http://localhost:8090
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path


def _load_combined_json(path: str) -> dict:
    raw = Path(path).read_text(encoding="utf-8")
    # Some historical logs contain leading text lines before the JSON object.
    start = raw.find("{")
    if start != -1:
        data = json.loads(raw[start:])
    else:
        data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object in {path}, got {type(data).__name__}")
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Import combined transcription JSON into Find it",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("video_id", help="Video id from the upload catalogue")
    parser.add_argument(
        "--json", required=True,
        help="Combined JSON file with 'frame_descriptions' and 'transcriptions' keys",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8090",
        help="Base URL of the Find it API (default: http://127.0.0.1:8090)",
    )

    args = parser.parse_args()

    data = _load_combined_json(args.json)
    payload = {
        "frame_descriptions": data.get("frame_descriptions", []),
        "transcriptions": data.get("transcriptions", []),
    }

    url = f"{args.base_url}/videos/{args.video_id}/transcriptions/import"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"import failed ({exc.code}): {exc.read().decode('utf-8')}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Imported for video {body['video_id']}: "
        f"{body['frames_imported']} frame(s), {body['audio_imported']} audio segment(s)"
    )


if __name__ == "__main__":
    main()
