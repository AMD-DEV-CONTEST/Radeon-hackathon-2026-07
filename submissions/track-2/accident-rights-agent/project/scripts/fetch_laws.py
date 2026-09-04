"""Download and verify only allow-listed official legal sources.

The curated article snapshots remain the deterministic index input.  These
downloads prove source availability and record a content hash without silently
substituting mirrors when an authority site is unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


ALLOWED_HOSTS = {
    "flk.npc.gov.cn",
    "wb.flk.npc.gov.cn",
    "jtgl.beijing.gov.cn",
    "xzfg.moj.gov.cn",
    "www.moj.gov.cn",
    "www.court.gov.cn",
    "gongbao.court.gov.cn",
    "openstd.samr.gov.cn",
    "std.samr.gov.cn",
    "www.samr.gov.cn",
    "ywtb.mps.gov.cn",
    "www.sdcourt.gov.cn",
    "gxj.ankang.gov.cn",
    "www.ym.gov.cn",
    "jjzd.yiyang.gov.cn",
}


def normalize_text(content: bytes, content_type: str) -> str:
    if "pdf" in content_type.lower() or content.startswith(b"%PDF-"):
        return ""
    decoded = content.decode("utf-8", errors="replace")
    return " ".join(BeautifulSoup(decoded, "html.parser").get_text(" ").split())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/laws/source_manifest.json")
    )
    parser.add_argument(
        "--snapshot-dir", type=Path, default=Path("data/laws/snapshots")
    )
    parser.add_argument(
        "--report", type=Path, default=Path("data/laws/source_verification.json")
    )
    parser.add_argument("--minimum-verified", type=int, default=10)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.snapshot_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    timeout = httpx.Timeout(30.0, connect=15.0)
    headers = {"User-Agent": "AccidentRightsAgent-LegalCorpus/0.1"}
    with httpx.Client(
        follow_redirects=True, timeout=timeout, headers=headers
    ) as client:
        for document in manifest["documents"]:
            url = document.get("verification_url", document["source_url"])
            requested_host = (urlparse(url).hostname or "").lower()
            result: dict[str, object] = {
                "document_id": document["document_id"],
                "source_url": document["source_url"],
                "verification_url": url,
                "expected_title": document["expected_title"],
                "verified": False,
            }
            if requested_host not in ALLOWED_HOSTS:
                result["error"] = f"host is not allow-listed: {requested_host}"
                results.append(result)
                continue
            try:
                response = client.get(url)
                response.raise_for_status()
                final_host = (response.url.host or "").lower()
                if final_host not in ALLOWED_HOSTS:
                    raise ValueError(f"redirected to non-official host: {final_host}")
                body = response.content
                if len(body) < 256:
                    raise ValueError("official response is unexpectedly small")
                content_type = response.headers.get("content-type", "")
                text = normalize_text(body, content_type)
                title_found = document["expected_title"].replace(" ", "") in text.replace(
                    " ", ""
                )
                suffix = ".pdf" if (
                    "pdf" in content_type.lower() or body.startswith(b"%PDF-")
                ) else ".html"
                snapshot = args.snapshot_dir / f"{document['document_id']}{suffix}"
                snapshot.write_bytes(body)
                result.update(
                    {
                        "verified": bool(title_found or suffix == ".pdf"),
                        "title_found": title_found,
                        "http_status": response.status_code,
                        "final_url": str(response.url),
                        "content_type": content_type,
                        "size_bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "snapshot": str(snapshot),
                    }
                )
                if not result["verified"]:
                    result["error"] = "expected title not found in official response"
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
            results.append(result)
    verified = sum(1 for item in results if item["verified"])
    report = {
        "manifest": str(args.manifest),
        "official_allowlist": sorted(ALLOWED_HOSTS),
        "total": len(results),
        "verified": verified,
        "minimum_verified": args.minimum_verified,
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if verified >= args.minimum_verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
