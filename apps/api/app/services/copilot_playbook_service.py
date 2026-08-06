"""Copilot Playbook service — seed, load, and match troubleshooting entries."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.copilot_playbook import CopilotPlaybook

_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "copilot_playbooks_seed.json"

# Audience tags for playbook cards (customer / developer / cloud).
PLAYBOOK_AUDIENCE: Dict[str, List[str]] = {
    "local_agent_unreachable": ["customer", "developer"],
    "python_venv_missing": ["customer"],
    "python_dev_missing": ["customer"],
    "pip_install_slow": ["customer"],
    "github_clone_slow": ["customer"],
    "dialout_missing": ["customer"],
    "no_cameras": ["customer"],
    "camera_busy": ["customer"],
    "no_serial": ["customer"],
    "robots_api_error": ["customer", "cloud"],
    "cloud_ssl_mismatch": ["customer", "cloud"],
    "database_error": ["cloud"],
    "training_auth_required": ["customer", "cloud"],
    "qualia_not_configured": ["cloud"],
    "lerobot_missing": ["customer"],
    "vite_dev_not_running": ["developer"],
    "port_8002_in_use": ["customer", "developer"],
    "llm_provider_disabled": ["cloud"],
    "llm_call_failed": ["cloud"],
    "cloud_api_unreachable": ["cloud"],
    "training_job_failed": ["customer", "cloud"],
}


def seed_playbooks(db: Session) -> int:
    """Insert default playbooks if table is empty. Returns count inserted."""
    existing = db.query(CopilotPlaybook).count()
    if existing > 0:
        return 0

    raw = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    for entry in raw:
        payload = {k: v for k, v in entry.items() if k != "audience"}
        db.add(CopilotPlaybook(**payload))
    db.commit()
    return len(raw)


def list_playbooks(db: Session, enabled_only: bool = True) -> List[CopilotPlaybook]:
    q = db.query(CopilotPlaybook)
    if enabled_only:
        q = q.filter(CopilotPlaybook.enabled.is_(True))
    return q.all()


def playbook_to_dict(pb: CopilotPlaybook) -> Dict[str, Any]:
    audience = PLAYBOOK_AUDIENCE.get(pb.code, ["customer"])
    return {
        "code": pb.code,
        "title": pb.title,
        "severity": pb.severity,
        "pages": pb.pages or [],
        "symptoms": pb.symptoms or [],
        "root_cause": pb.root_cause,
        "fix_steps": pb.fix_steps or [],
        "verify_steps": pb.verify_steps or [],
        "safe_to_show": pb.safe_to_show,
        "audience": audience,
    }


def _get_nested(data: Dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _eval_diagnostic_key(
    key: str,
    server_diag: Dict[str, Any],
    client_diag: Optional[Dict[str, Any]],
    page: str,
) -> bool:
    if key.startswith("issue:"):
        code = key.split(":", 1)[1]
        return any(i.get("code") == code for i in server_diag.get("issues", []))

    if key.startswith("error:"):
        fragment = key.split(":", 1)[1].lower()
        errs = (client_diag or {}).get("recentErrors") or []
        return any(fragment in e.lower() for e in errs)

    if key.startswith("runtime."):
        rt = server_diag.get("runtime") or {}
        expr = key[len("runtime.") :]
        if "=" in expr:
            field, expected = expr.split("=", 1)
            actual = rt.get(field)
            if expected in ("true", "false"):
                return str(actual).lower() == expected
            try:
                return str(actual) == expected
            except Exception:
                return False
        return bool(rt.get(expr))

    if key.startswith("server."):
        expr = key[len("server.") :]
        if "=" in expr:
            field, expected = expr.split("=", 1)
            actual = _get_nested(server_diag, field)
            if expected in ("true", "false"):
                return str(actual).lower() == expected
            return str(actual) == expected
        return bool(_get_nested(server_diag, expr))

    if key.startswith("client."):
        expr = key[len("client.") :]
        if "=" in expr:
            field, expected = expr.split("=", 1)
            actual = _get_nested(client_diag or {}, field)
            if expected in ("true", "false"):
                return str(actual).lower() == expected
            return str(actual) == expected
        return bool(_get_nested(client_diag or {}, expr))

    return False


def _page_matches(pages: List[str], page: str) -> bool:
    if not pages:
        return True
    if not page:
        return True
    return any(p in page for p in pages)


def _symptom_matches(symptoms: List[str], text: str) -> bool:
    if not text or not symptoms:
        return False
    lower = text.lower()
    return any(s.lower() in lower for s in symptoms)


def match_playbooks(
    db: Session,
    *,
    server_diag: Dict[str, Any],
    client_diag: Optional[Dict[str, Any]] = None,
    page: str = "",
    user_message: str = "",
) -> List[Dict[str, Any]]:
    """Return matched playbooks sorted by severity (error > warning > info)."""
    playbooks = list_playbooks(db)
    matched: List[tuple[int, CopilotPlaybook]] = []
    severity_rank = {"error": 0, "warning": 1, "info": 2}

    combined_text = user_message
    if client_diag:
        combined_text += " " + " ".join(client_diag.get("recentErrors") or [])
        la_err = (client_diag.get("localAgent") or {}).get("error") or ""
        combined_text += " " + la_err

    for pb in playbooks:
        score = 0
        keys = pb.diagnostic_keys or []
        if keys:
            hits = sum(
                1
                for k in keys
                if _eval_diagnostic_key(k, server_diag, client_diag, page)
            )
            if hits == 0:
                continue
            score += hits * 10

        if pb.pages and page and not _page_matches(pb.pages, page):
            if not keys:
                continue

        if user_message and _symptom_matches(pb.symptoms or [], combined_text):
            score += 5

        if not keys and not _symptom_matches(pb.symptoms or [], combined_text):
            if pb.pages and _page_matches(pb.pages, page):
                issue_codes = {i.get("code") for i in server_diag.get("issues", [])}
                if pb.code.replace("_", "") in "".join(issue_codes):
                    score += 3
                else:
                    continue
            else:
                continue

        if score > 0 or keys:
            if score == 0 and keys:
                score = 1
            matched.append((score, pb))

    seen: set[str] = set()
    results: List[Dict[str, Any]] = []
    for _, pb in sorted(
        matched,
        key=lambda x: (severity_rank.get(x[1].severity, 9), -x[0], x[1].code),
    ):
        if pb.code in seen:
            continue
        seen.add(pb.code)
        results.append(playbook_to_dict(pb))

    return results


def format_playbook_answer(matches: List[Dict[str, Any]]) -> str:
    if not matches:
        return ""
    lines: List[str] = []
    for m in matches[:3]:
        lines.append(f"【{m['title']}】")
        lines.append(f"原因：{m['root_cause']}")
        lines.append("修复步骤：")
        for i, step in enumerate(m.get("fix_steps") or [], 1):
            lines.append(f"  {i}. {step}")
        if m.get("verify_steps"):
            lines.append("验证：")
            for step in m["verify_steps"]:
                lines.append(f"  - {step}")
        lines.append("")
    return "\n".join(lines).strip()


def safe_diagnostic_summary(
    server_diag: Dict[str, Any],
    client_diag: Optional[Dict[str, Any]],
    page: str,
) -> Dict[str, Any]:
    """Metadata safe to show users before sending to LLM."""
    summary: Dict[str, Any] = {
        "page": page,
        "overall": server_diag.get("overall"),
        "checks": {
            "cloud_api": server_diag.get("cloud_api", {}).get("ok"),
            "database": server_diag.get("database", {}).get("ok"),
            "realtime": server_diag.get("realtime", {}).get("ok"),
            "robots": server_diag.get("robots", {}).get("ok"),
            "llm_enabled": server_diag.get("llm_enabled"),
        },
        "issue_codes": [i.get("code") for i in server_diag.get("issues", [])],
    }
    if client_diag:
        summary["client"] = {
            "local_agent_ok": (client_diag.get("localAgent") or {}).get("ok"),
            "recent_error_count": len(client_diag.get("recentErrors") or []),
        }
    rt = server_diag.get("runtime") or {}
    if rt:
        summary["runtime"] = {
            "cameras": f"{rt.get('camera_usable_count', '?')}/{rt.get('video_device_count', '?')}",
            "serial_devices": rt.get("serial_device_count", 0),
            "dialout": rt.get("dialout_member"),
            "lerobot": rt.get("lerobot_available"),
        }
    return summary
