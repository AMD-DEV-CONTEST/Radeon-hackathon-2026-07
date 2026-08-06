from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    endpoint = os.environ.get("ALPHANOAH_BASE_URL", "").rstrip("/")
    if not endpoint:
        print("Provider Health: FAIL")
        return 1
    path = "/api/tags" if os.environ.get("ALPHANOAH_PROVIDER") == "ollama" else "/models"
    request = urllib.request.Request(endpoint + path)
    key = os.environ.get("ALPHANOAH_API_KEY", "")
    if key:
        request.add_header("Authorization", "Bearer " + key)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        print("Provider Health: FAIL")
        return 1
    if not isinstance(payload, dict):
        print("Provider Health: FAIL")
        return 1
    print("Provider Health: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
