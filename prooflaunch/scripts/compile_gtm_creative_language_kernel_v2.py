#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_creative_language_kernel_v2 import build_creative_language_kernel, verify_creative_language_kernel


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    payload = build_creative_language_kernel(); verify_creative_language_kernel(payload)
    output = ROOT / "evidence/v10/gtm-creative-language-kernel-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "territory_count": len(payload["creative_territories"]), "platform_standard_count": len(payload["platform_writing_standards"]), "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
