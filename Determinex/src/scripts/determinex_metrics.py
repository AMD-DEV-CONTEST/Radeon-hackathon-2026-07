#!/usr/bin/env python3
"""determinex_metrics.py — Prometheus metrics exporter for Determinex.

Exposes /metrics on port 9101. Reads from determinex.db + Hetzner queue state.

Metrics:
- determinex_pool_done_total
- determinex_pool_pending_total{tier="light|heavy"}
- determinex_pool_claimed_total
- determinex_evals_total
- determinex_score_pct{instance_id="..."}
- determinex_score_bucket_total{bucket="..."}
- determinex_eval_duration_seconds{instance_id="...", quantile="0.5|0.95"}

Run:
    python scripts/determinex_metrics.py --port 9101
"""

from __future__ import annotations

import argparse
import http.server
import sqlite3
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "logs" / "determinex.db"


def collect() -> str:
    out = []

    # ── DB metrics ─────────────────────────────────────────────
    if DB.exists():
        try:
            c = sqlite3.connect(DB)
            cur = c.cursor()
            n = cur.execute("SELECT COUNT(*) FROM evals").fetchone()[0]
            out.append("# HELP determinex_evals_total Total eval records")
            out.append("# TYPE determinex_evals_total counter")
            out.append(f"determinex_evals_total {n}")

            # Latest per tool
            cur.execute("""
                SELECT e.instance_id, e.pct, e.duration_s
                FROM evals e
                WHERE e.ran_at = (SELECT MAX(ran_at) FROM evals e2 WHERE e2.instance_id = e.instance_id)
                AND e.pct IS NOT NULL
            """)
            buckets = {"95_100": 0, "70_94": 0, "40_69": 0, "10_39": 0, "0_9": 0}
            out.append("# HELP determinex_score_pct Score per tool (latest)")
            out.append("# TYPE determinex_score_pct gauge")
            for inst, pct, dur in cur.fetchall():
                # Escape label
                ie = inst.replace("\\", "\\\\").replace('"', '\\"')
                out.append(f'determinex_score_pct{{instance_id="{ie}"}} {pct}')
                if pct >= 95:
                    buckets["95_100"] += 1
                elif pct >= 70:
                    buckets["70_94"] += 1
                elif pct >= 40:
                    buckets["40_69"] += 1
                elif pct >= 10:
                    buckets["10_39"] += 1
                else:
                    buckets["0_9"] += 1
                if dur:
                    out.append(f'determinex_eval_duration_seconds{{instance_id="{ie}"}} {dur}')

            out.append("# HELP determinex_score_bucket_total Tools in each score bucket")
            out.append("# TYPE determinex_score_bucket_total gauge")
            for b, n in buckets.items():
                out.append(f'determinex_score_bucket_total{{bucket="{b}"}} {n}')

            c.close()
        except Exception as e:
            out.append(f"# ERROR reading DB: {e}")

    # ── Hetzner queue (via SSH) ─────────────────────────────────
    try:
        result = subprocess.run(
            [
                "ssh",
                "-i",
                str(Path.home() / ".ssh" / "id_citadel"),
                "-o",
                "ConnectTimeout=3",
                "root@5.78.192.163",
                "wc -l /root/queue/pending_light.txt /root/queue/pending_heavy.txt /root/queue/claimed.txt /root/queue/done.txt 2>/dev/null",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            out.append("# HELP determinex_pool_count Pool state counts")
            out.append("# TYPE determinex_pool_count gauge")
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) < 2:
                    continue
                n = parts[0]
                if "pending_light" in parts[1]:
                    out.append(f'determinex_pool_count{{state="pending",tier="light"}} {n}')
                elif "pending_heavy" in parts[1]:
                    out.append(f'determinex_pool_count{{state="pending",tier="heavy"}} {n}')
                elif "claimed" in parts[1]:
                    out.append(f'determinex_pool_count{{state="claimed",tier="all"}} {n}')
                elif "done" in parts[1]:
                    out.append(f'determinex_pool_count{{state="done",tier="all"}} {n}')
    except Exception:
        pass

    out.append("# HELP determinex_collector_last_run Unix timestamp of last metrics collection")
    out.append("# TYPE determinex_collector_last_run gauge")
    out.append(f"determinex_collector_last_run {int(time.time())}")
    return "\n".join(out) + "\n"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = collect().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"determinex_metrics -- visit /metrics\n")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a, **k):
        pass  # silence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9101)
    args = ap.parse_args()
    srv = http.server.HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"determinex_metrics listening on :{args.port}/metrics")
    srv.serve_forever()


if __name__ == "__main__":
    main()
