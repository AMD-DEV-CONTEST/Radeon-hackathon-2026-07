"""Check SparkFencer's local-only runtime prerequisites.

Run: python scripts/health_check.py
"""

import json
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fencing_analysis.config import load_config


def port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def main():
    cfg = load_config(os.path.join(ROOT, "config.yaml"))
    report = {
        "local_only": cfg.get("privacy", {}).get("local_only", False),
        "agent_backend": cfg["agents"]["backend"],
        "knowledge_index": os.path.isdir(os.path.join(ROOT, "knowledge", ".index")),
        "outputs_writable": os.access(os.path.join(ROOT, "outputs"), os.W_OK),
        "model_endpoint": cfg["agents"]["local"]["base_url"],
        "model_endpoint_reachable": port_open("127.0.0.1", 11434),
    }
    try:
        import torch
        report["torch_version"] = torch.__version__
        report["accelerator_available"] = torch.cuda.is_available()
        if report["accelerator_available"]:
            report["accelerator_name"] = torch.cuda.get_device_name(0)
            report["hip_version"] = getattr(torch.version, "hip", None)
    except Exception as exc:
        report["torch_error"] = str(exc)
    required = (report["local_only"] and report["agent_backend"] == "local"
                and report["knowledge_index"] and report["outputs_writable"])
    report["ready"] = bool(required)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
