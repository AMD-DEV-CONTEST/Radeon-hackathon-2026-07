"""
Candidate Persistence Registry & Flight Recorder Integration.
Persists approved candidate metadata in JSON format and appends SHA-256 HMAC chained audit log entries via the FlightRecorder.append() API.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from core.audit.flight_recorder import audit_enabled


class CandidateRegistry:
    def __init__(self, registry_file: Optional[Path] = None):
        current_file = Path(__file__).resolve()
        self.registry_file = registry_file or (current_file.parent / "registry.json")
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self.registry_file.exists():
            with open(self.registry_file, "w", encoding="utf-8") as f:
                json.dump({"candidates": []}, f, indent=2)

    def register_candidate(self, candidate_data: Dict[str, Any]) -> str:
        with open(self.registry_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        cand_id = f"cand_{candidate_data.get('kernel_name', 'kernel')}_{len(data['candidates']) + 1:03d}"
        candidate_data["id"] = cand_id
        data["candidates"].append(candidate_data)

        with open(self.registry_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        if audit_enabled():
            try:
                from core.audit.flight_recorder import get_recorder
                rec = get_recorder("cli_session")
                rec.append("candidate_registered", candidate_data, actor="optimizer")
            except Exception:
                pass

        return cand_id

    def get_candidates(self) -> List[Dict[str, Any]]:
        if not self.registry_file.exists():
            return []
        with open(self.registry_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("candidates", [])
