"""
HTTP and SSE client for communication with the Aetheris Studio backend server.
Handles authentication token discovery, endpoint invocation, SSE stream generation, model selection, warmup status querying, Cartographer status querying, Flight Recorder audit log retrieval, SHA-256 hash chain verification, and tool confirmation execution.
"""

import os
from typing import Any, Dict, Iterator, List, Optional
import requests

from aetheris_cli.transport.events import SSEEvent, parse_sse_stream_lines


class AetherisClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8001", token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.token = token or self._resolve_token()
        self.session = requests.Session()
        self.session.headers.update({
            "X-Internal-Token": self.token,
            "Content-Type": "application/json",
        })

    def _resolve_token(self) -> str:
        env_token = os.environ.get("AETHERIS_INTERNAL_TOKEN")
        if env_token:
            return env_token

        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
        env_file_path = os.path.join(project_root, ".env")

        if os.path.exists(env_file_path):
            with open(env_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("AETHERIS_INTERNAL_TOKEN="):
                        return stripped.split("=", 1)[1].strip("\"'")

        return ""

    def is_backend_alive(self) -> bool:
        try:
            resp = self.session.get(f"{self.base_url}/", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def get_health(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/api/health", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def get_telemetry(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/api/telemetry", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def get_warmup_status(self) -> Dict[str, Any]:
        try:
            resp = self.session.get(f"{self.base_url}/api/warmup-status", timeout=2)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {"warming_up": False}

    def get_egress_status(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/api/egress/status", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def set_default_model(self, model: str) -> Dict[str, Any]:
        if not model:
            return {}
        try:
            resp = self.session.post(f"{self.base_url}/api/settings", json={"default_model": model}, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {}

    def set_project_path(self, path: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"path": path}
        if chat_id:
            payload["chat_id"] = chat_id
        resp = self.session.post(f"{self.base_url}/api/project-path", json=payload, timeout=5)
        resp.raise_for_status()
        return resp.json()

    def reload_vte(self) -> Dict[str, Any]:
        """Asks the backend to unload the resident production vte-server
        subprocess (see app.py's /api/optimizer/reload-vte) so it respawns
        fresh on the next chat message -- needed after promoting a kernel
        optimizer candidate, since a running vte-server keeps using
        whatever it already loaded regardless of template file changes."""
        resp = self.session.post(f"{self.base_url}/api/optimizer/reload-vte", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def list_snapshots(self, session_id: str) -> Dict[str, Any]:
        """Time-Travel timeline for a session: every shadow-ref snapshot,
        newest first (see core/audit/timetravel.py::list_snapshots). Each
        entry carries {commit, ts, message, turn_id, paths}.

        NOTE: the backend resolves snapshots against its OWN active project
        (an env var in the backend process), so callers must
        set_project_path() first or this legitimately returns an empty
        list for a project the backend isn't currently pointed at."""
        resp = self.session.get(f"{self.base_url}/api/timetravel/{session_id}/snapshots", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def preview_checkpoint(self, session_id: str, turn_id: int) -> Dict[str, Any]:
        """Read-only: the combined diff of restoring the project to the
        state it had before user message `turn_id`. Touches nothing."""
        resp = self.session.post(
            f"{self.base_url}/api/timetravel/checkpoint/preview",
            json={"session_id": session_id, "turn_id": turn_id},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def restore_checkpoint(self, session_id: str, turn_id: int) -> Dict[str, Any]:
        """The actual message-anchored undo. Deliberately does NOT swallow
        transport errors the way the read-only helpers above do: a restore
        that silently reported success while changing nothing would be far
        worse than a loud failure."""
        resp = self.session.post(
            f"{self.base_url}/api/timetravel/checkpoint/restore",
            json={"session_id": session_id, "turn_id": turn_id},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def get_cartographer_status(self) -> Dict[str, Any]:
        try:
            resp = self.session.get(f"{self.base_url}/api/cartographer/status", timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {"mapped": 0, "structural_only": 0, "total": 0, "state": "idle"}

    def get_audit_trail(self, session_id: str) -> Dict[str, Any]:
        try:
            resp = self.session.get(f"{self.base_url}/api/audit/{session_id}", timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"entries": [], "error": str(e)}

    def verify_session(self, session_id: str) -> Dict[str, Any]:
        try:
            resp = self.session.get(f"{self.base_url}/api/audit/{session_id}/verify", timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"valid": False, "reason": str(e)}

    def execute_tool(
        self, tool: str, content: str, chat_id: Optional[str] = None, turn_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """`turn_id` stamps the Time-Travel snapshot this edit takes with
        the user message that proposed it (see app.py's
        ExecuteToolRequest.turn_id). Omitting it is not cosmetic: a
        snapshot with no turn is never a checkpoint boundary, so the edit
        becomes invisible to `aetheris undo`."""
        payload: Dict[str, Any] = {"tool": tool, "content": content}
        if chat_id:
            payload["chat_id"] = chat_id
        if turn_id is not None:
            payload["turn_id"] = turn_id
        resp = self.session.post(f"{self.base_url}/api/tools/execute", json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def decline_tool(self, tool: str, content: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"tool": tool, "content": content}
        if chat_id:
            payload["chat_id"] = chat_id
        resp = self.session.post(f"{self.base_url}/api/tools/decline", json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def stream_chat(
        self,
        messages: List[Dict[str, str]],
        mode: str = "builder",
        chat_id: Optional[str] = None,
        model: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        turn_id: Optional[int] = None,
        timeout: int = 300,
    ) -> Iterator[SSEEvent]:
        payload: Dict[str, Any] = {
            "messages": messages,
            "mode": mode,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if model:
            payload["model"] = model
        if chat_id:
            payload["chat_id"] = chat_id
        if turn_id is not None:
            payload["turn_id"] = turn_id

        resp = self.session.post(
            f"{self.base_url}/v1/chat/completions/stream",
            json=payload,
            stream=True,
            timeout=timeout,
        )
        resp.raise_for_status()

        return parse_sse_stream_lines(resp.iter_lines(decode_unicode=True))
