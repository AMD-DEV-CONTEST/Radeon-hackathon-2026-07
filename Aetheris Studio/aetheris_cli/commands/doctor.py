"""
Environment diagnostic subcommand implementation (aetheris doctor).
Inspects backend system health, GPU hardware telemetry, VTE engine state, and egress status.
"""

import json
import sys
from typing import Any, Dict
from aetheris_cli.transport.backend import check_backend_availability
from aetheris_cli.transport.client import AetherisClient


def doctor_command(json_mode: bool = False) -> int:
    client = AetherisClient()
    report: Dict[str, Any] = {
        "backend_online": False,
        "health": {},
        "telemetry": {},
        "egress": {},
    }

    ok, msg = check_backend_availability(client)
    report["backend_online"] = ok
    report["backend_message"] = msg

    if ok:
        try:
            report["health"] = client.get_health()
        except Exception as e:
            report["health"] = {"error": str(e)}

        try:
            report["telemetry"] = client.get_telemetry()
        except Exception as e:
            report["telemetry"] = {"error": str(e)}

        try:
            report["egress"] = client.get_egress_status()
        except Exception as e:
            report["egress"] = {"error": str(e)}

    if json_mode:
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write("=== Aetheris System Doctor ===\n")
        sys.stdout.write(f"Backend Status: {'ONLINE' if ok else 'OFFLINE'} ({msg})\n")
        
        if ok:
            h = report.get("health", {})
            t = report.get("telemetry", {})
            e = report.get("egress", {})

            sys.stdout.write(f"VTE Engine Model: {t.get('loaded_model') or h.get('model') or 'N/A'}\n")
            sys.stdout.write(f"VRAM Allocated: {t.get('vram_allocated_mb', 0)} MB\n")
            sys.stdout.write(f"Egress Connections Detected: {e.get('external_connections', 0)}\n")

    return 0 if ok else 3
