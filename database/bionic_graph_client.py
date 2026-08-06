"""HTTP client for the Bionic-Graph engine (Rust, Gremlin-compatible).

Reference deployment/API: /home/pdfexe/neo4j/bionic-graph/AGENTS.md

Quirks handled here (see AGENTS.md "Known quirks/bugs"):
- `/gremlin` and `/search` responses are wrapped in {"success","data","error"};
  we unwrap `.data` and raise on `success == False`.
- Exact search can return the same entity multiple times -> we dedup by id.
- The token index is append-only (removing a keyword still matches it) -> callers
  should use STABLE, UNIQUE entity names (e.g. "person:Alice") and keep mutable
  info in `properties`, never in `keywords`, so a renamed/retyped entity does not
  keep matching its old keywords.
- `V` + rank-based `limit` may under-return vertices (rank index mixes vertices and
  edges) -> when an exact count matters, query by explicit ids then limit.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable


DEFAULT_BASE_URL = "http://127.0.0.1:8088"
DEFAULT_GRAPH = "graph0"


class BionicGraphError(RuntimeError):
    """Raised on HTTP errors or graph-level failures (success == False)."""


def _dedup_by_id(items: Iterable[dict]) -> list[dict]:
    """Dedup Bionic-Graph results by vertex/edge id (exact search duplicates)."""
    out: dict[Any, dict] = {}
    for it in items:
        key = it.get("id")
        if key is None:
            out[id(it)] = it
        else:
            out.setdefault(key, it)
    return list(out.values())


class BionicGraphClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        graph: str = DEFAULT_GRAPH,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.graph = graph
        self.timeout = timeout

    # -- low level ---------------------------------------------------------
    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Content-Type": "application/json", "X-Graph-Name": self.graph}
        if extra:
            h.update(extra)
        return h

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
        query: dict | None = None,
    ) -> Any:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(json_body).encode() if json_body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method, headers=self._headers()
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            raise BionicGraphError(f"{method} {path} -> HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise BionicGraphError(f"{method} {path} -> {e.reason}") from e
        return json.loads(raw) if raw else None

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        """Unwrap {"success","data","error"} envelopes; pass through raw results."""
        if isinstance(payload, dict) and ("success" in payload or "error" in payload):
            if payload.get("success") is False:
                raise BionicGraphError(payload.get("error") or "graph op failed")
            return payload.get("data")
        return payload

    # -- graph management --------------------------------------------------
    def health(self) -> dict:
        return self._request("GET", "/health") or {}

    def list_graphs(self) -> list:
        return self._unwrap(self._request("GET", "/graphs")) or []

    def create_graph(self, name: str, time_travel: bool = True) -> dict:
        return self._unwrap(
            self._request(
                "POST", "/graphs", {"name": name, "time_travel": time_travel}
            )
        ) or {}

    def delete_graph(self, name: str) -> Any:
        return self._unwrap(self._request("DELETE", f"/graphs/{name}"))

    # -- vertices ----------------------------------------------------------
    def create_vertex(
        self,
        name: str,
        labels: list[str] | None = None,
        keywords: list[str] | None = None,
        properties: dict | None = None,
    ) -> int:
        body = {"name": name}
        if labels is not None:
            body["labels"] = labels
        if keywords is not None:
            body["keywords"] = keywords
        if properties is not None:
            body["properties"] = properties
        result = self._unwrap(self._request("POST", "/vertices", body)) or {}
        vid = result.get("id")
        if vid is None:
            raise BionicGraphError(f"create_vertex returned no id: {result}")
        return int(vid)

    def update_vertex(self, vid: int, **fields) -> Any:
        return self._unwrap(self._request("PUT", f"/vertices/{vid}", fields))

    def vertex_meta(self, vid: int) -> dict:
        return self._unwrap(self._request("GET", f"/vertices/{vid}/meta")) or {}

    def delete_vertex(self, vid: int, force: bool = True) -> Any:
        return self._unwrap(
            self._request("DELETE", f"/vertices/{vid}", query={"force": "true"} if force else None)
        )

    # -- edges -------------------------------------------------------------
    def create_edge(
        self,
        source: int,
        target: int,
        name: str,
        strength: float | None = None,
        properties: dict | None = None,
    ) -> int:
        body: dict[str, Any] = {"source": source, "target": target, "name": name}
        if strength is not None:
            body["strength"] = strength
        if properties is not None:
            body["properties"] = properties
        result = self._unwrap(self._request("POST", "/edges", body)) or {}
        eid = result.get("id")
        if eid is None:
            raise BionicGraphError(f"create_edge returned no id: {result}")
        return int(eid)

    def update_edge(self, eid: int, **fields) -> Any:
        return self._unwrap(self._request("PUT", f"/edges/{eid}", fields))

    # -- query -------------------------------------------------------------
    def gremlin(self, steps: list[dict]) -> Any:
        return self._unwrap(self._request("POST", "/gremlin", {"steps": steps}))

    def search(
        self,
        text: str,
        mode: str = "greedy",
        limit: int = 10,
        dedup: bool = True,
    ) -> list:
        data = self._unwrap(
            self._request(
                "GET",
                "/search",
                query={"text": text, "mode": mode, "limit": str(limit)},
            )
        ) or []
        return _dedup_by_id(data) if dedup else data

    # -- batch -------------------------------------------------------------
    def batch_load(
        self,
        entities: list[dict] | None = None,
        relations: list[dict] | None = None,
        update_existing: bool = True,
    ) -> Any:
        body: dict[str, Any] = {"update_existing": update_existing}
        if entities is not None:
            body["entities"] = entities
        if relations is not None:
            body["relations"] = relations
        return self._unwrap(self._request("POST", "/batch/load", body))
