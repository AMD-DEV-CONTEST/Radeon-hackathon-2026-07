#!/usr/bin/env python3
"""
determinex_key_proxy.py -- local API key-injecting proxy for the on-box reimpl engine.

The autonomous reimpl engine runs ON the Hetzner box (native toolchain + docker images live
there), but the model API key must NEVER leave the operator machine (release rule: no uploaded
keys, no hardcoding). This proxy bridges the gap:

  box engine --(SSH reverse tunnel  -R 18080:localhost:18080)--> THIS proxy (local)
                                                                  --> https://api.deepseek.com
                                                                      (Authorization injected here)

So the box sends key-less requests to localhost:18080 (the tunnel); this local proxy injects
the Bearer token from the LOCAL .env and forwards upstream. The key stays on the operator box.

Run:
  python scripts/determinex_key_proxy.py            # listens 127.0.0.1:18080, upstream deepseek
Then SSH to the box with:  ssh -R 18080:localhost:18080 ...
and on the box export:      DETERMINEX_DEEPSEEK_HOST=http://localhost:18080
"""

from __future__ import annotations

import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("DETERMINEX_PROXY_UPSTREAM", "https://api.deepseek.com")
PORT = int(os.environ.get("DETERMINEX_PROXY_PORT", "18080"))


def _load_key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY", "")
    if k:
        return k
    # fall back to .env next to the repo root
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        for ln in open(os.path.join(root, ".env"), encoding="utf-8"):
            if ln.strip().startswith("#") or "=" not in ln:
                continue
            name, val = ln.split("=", 1)
            if name.strip() == "DEEPSEEK_API_KEY":
                return val.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return ""


KEY = _load_key()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    def _proxy(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        url = UPSTREAM + self.path
        req = urllib.request.Request(url, data=body, method=self.command)
        req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
        if KEY:
            req.add_header("Authorization", f"Bearer {KEY}")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
                self.send_response(r.status)
                self.send_header("Content-Type", r.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            msg = f'{{"error":"proxy_error: {e}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_POST(self):
        self._proxy()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self._proxy()


def main() -> int:
    if not KEY:
        print(
            "WARN: no DEEPSEEK_API_KEY found locally; proxy will forward without auth",
            file=sys.stderr,
        )
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(
        f"[key-proxy] listening 127.0.0.1:{PORT} -> {UPSTREAM} (key {'loaded' if KEY else 'MISSING'})"
    )
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
