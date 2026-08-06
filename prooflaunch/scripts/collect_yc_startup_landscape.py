#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from prooflaunch_remix.gtm_startup_landscape import (
    compile_startup_distillation_queue,
    compile_startup_landscape,
    parse_yc_directory_page,
    verify_startup_distillation_queue,
    verify_startup_landscape,
)


COHORT_URLS = {
    "b2b": "https://www.ycombinator.com/companies/industry/b2b",
    "b2c": "https://www.ycombinator.com/companies/industry/consumer",
}


def page_url(base_url: str, page: int) -> str:
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query))
    if page > 1:
        query["page"] = str(page)
    else:
        query.pop("page", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def fetch_text(url: str, *, timeout: int = 45, attempts: int = 4) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "ProofLaunchEvidenceResearch/1.0 (+read-only public directory audit)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # network errors vary across runtimes
            error = exc
            if attempt + 1 < attempts:
                time.sleep(min(8, 2**attempt))
    raise RuntimeError(f"failed to fetch {url}: {error}")


def collect_cohort(cohort: str, base_url: str, workers: int, max_pages: int | None) -> list[dict]:
    first_url = page_url(base_url, 1)
    first = parse_yc_directory_page(fetch_text(first_url), first_url, cohort)
    total_pages = first["total_pages"]
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)
        first["total_pages"] = total_pages
    pages = [first]
    if total_pages == 1:
        return pages
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_text, page_url(base_url, page)): (page, page_url(base_url, page))
            for page in range(2, total_pages + 1)
        }
        for future in as_completed(futures):
            page, url = futures[future]
            parsed = parse_yc_directory_page(future.result(), url, cohort)
            if max_pages is not None:
                parsed["total_pages"] = total_pages
            if parsed["current_page"] != page:
                raise RuntimeError(f"pagination mismatch for {url}")
            pages.append(parsed)
    return sorted(pages, key=lambda item: item["current_page"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect YC public B2B and Consumer directories into a bounded startup landscape.")
    parser.add_argument("--output", type=Path, default=Path("evidence/v10/gtm-startup-landscape-yc-v1.json"))
    parser.add_argument(
        "--queue-output",
        type=Path,
        default=Path("evidence/v10/gtm-startup-distillation-queue-yc-v1.json"),
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-pages", type=int, default=0, help="0 collects every page; positive values are test-only caps.")
    parser.add_argument("--minimum-records", type=int, default=3000)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("workers must be between 1 and 8")
    max_pages = args.max_pages or None
    pages: list[dict] = []
    for cohort, url in COHORT_URLS.items():
        cohort_pages = collect_cohort(cohort, url, args.workers, max_pages)
        pages.extend(cohort_pages)
        print(json.dumps({"cohort": cohort, "pages": len(cohort_pages), "records": sum(p["record_count"] for p in cohort_pages)}))
    landscape = compile_startup_landscape(pages, minimum_records=args.minimum_records)
    verify_startup_landscape(landscape)
    queue = compile_startup_distillation_queue(landscape)
    verify_startup_distillation_queue(queue, landscape)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(landscape, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.queue_output.parent.mkdir(parents=True, exist_ok=True)
    args.queue_output.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "landscape_output": str(args.output),
                "queue_output": str(args.queue_output),
                "record_count": landscape["record_count"],
                "coverage_cell_count": landscape["coverage_cell_count"],
                "distillation_audit_unit_count": queue["distillation_audit_unit_count"],
                "landscape_sha256": landscape["content_sha256"],
                "queue_sha256": queue["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
