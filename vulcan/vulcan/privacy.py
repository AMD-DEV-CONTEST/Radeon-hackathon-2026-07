"""Prove that nothing left the machine, instead of asserting it.

This track is about private agents, and Vulcan's whole claim is that no token
reaches a third party. A reader has to take that on trust: the code looks local,
the README says local, and neither is evidence. So this records every outbound
HTTP request made during a real agent run and checks each host against the
endpoints that were actually configured.

It hooks `httpx.Client.send`, which is the single choke point every request in
this project passes through, rather than trying to enumerate call sites. A new
one added later is caught without anyone remembering to update a list.

Two things it deliberately does not claim:

- It sees HTTP made through httpx, which is all of Vulcan's own traffic. It does
  not sandbox `run_cmd`, so a test suite the agent chooses to run could reach the
  network on its own account. That is the user's command, not the agent's, and
  the report says so rather than pretending otherwise.
- A local endpoint is trusted because it is the one you configured. If you point
  `VULCAN_BASE_URL` at a hosted API, this will faithfully report that host, which
  is the point.
"""
from __future__ import annotations

import contextlib
from urllib.parse import urlparse

import httpx


@contextlib.contextmanager
def record_hosts():
    """Collect the host of every httpx request made inside the block."""
    seen: list[str] = []
    original = httpx.Client.send

    def send(self, request, **kwargs):
        seen.append(request.url.host or "")
        return original(self, request, **kwargs)

    httpx.Client.send = send
    try:
        yield seen
    finally:
        httpx.Client.send = original


def allowed_hosts(cfg) -> set[str]:
    """The endpoints the user configured, and nothing else."""
    return {h for h in (urlparse(cfg.base_url).hostname,
                        urlparse(cfg.embed_base_url).hostname) if h}


def check(cfg, hosts: list[str]) -> dict:
    allowed = allowed_hosts(cfg)
    contacted = sorted(set(h for h in hosts if h))
    unexpected = sorted(h for h in contacted if h not in allowed)
    return {
        "requests": len(hosts),
        "hosts_contacted": contacted,
        "hosts_allowed": sorted(allowed),
        "unexpected": unexpected,
        "private": not unexpected,
    }


def mask_endpoint(url: str) -> str:
    """Elide the instance id from a Radeon Cloud URL.

    The instance id is the whole path to someone else's GPU budget: the tunnel
    takes no credentials, so the URL is the credential. It was already elided in
    the terminal banner, but `vulcan bench` wrote `cfg.base_url` verbatim into
    every result file, and those files are committed. The id reached a public
    repository that way. Masking belongs at the point of serialisation, not at
    the point of display.
    """
    head, _, tail = url.rstrip("/").rpartition("/spaces/")
    if not head:
        return url
    return f"{head}/spaces/<instance>/" + tail.split("/", 1)[-1]
