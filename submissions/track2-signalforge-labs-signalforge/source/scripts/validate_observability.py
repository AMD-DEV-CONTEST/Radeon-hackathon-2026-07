#!/usr/bin/env python3
"""Static validation for the privacy-safe Mission Control bundle."""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OBSERVABILITY = ROOT / "deploy" / "observability"

REQUIRED_DASHBOARDS = {
    "executive-journey.json": "signalforge-executive",
    "radeon-performance.json": "signalforge-radeon",
    "agent-orchestration.json": "signalforge-agents",
    "trust-evidence-privacy.json": "signalforge-trust",
}

FORBIDDEN_LABELS = {
    "run_id", "trace_id", "model_id", "ticker", "user", "prompt",
    "response", "source_url", "error_text", "question", "answer",
}


def fail(message: str) -> None:
    raise ValueError(message)


def validate_dashboards() -> None:
    dashboard_dir = OBSERVABILITY / "grafana" / "dashboards"
    for filename, uid in REQUIRED_DASHBOARDS.items():
        payload = json.loads((dashboard_dir / filename).read_text())
        if payload.get("uid") != uid:
            fail(f"{filename}: unexpected uid")
        if not payload.get("panels"):
            fail(f"{filename}: no panels")
        if payload.get("editable") is not False:
            fail(f"{filename}: dashboard must be immutable")
        serialized = json.dumps(payload)
        if "signalforge" not in serialized and "radeon_gpu" not in serialized:
            fail(f"{filename}: no real SignalForge or Radeon query")
    orchestration = json.loads(
        (dashboard_dir / "agent-orchestration.json").read_text()
    )
    panels = orchestration["panels"]
    if not any(
        panel.get("type") == "traces" and "Wave" in panel.get("title", "")
        for panel in panels
    ):
        fail("agent-orchestration.json: correlated wave waterfall is absent")
    if not any(
        panel.get("type") == "logs"
        and "orchestration" in json.dumps(panel.get("targets", []))
        for panel in panels
    ):
        fail("agent-orchestration.json: bounded lifecycle event panel is absent")


def validate_alloy_labels() -> None:
    alloy = (OBSERVABILITY / "alloy" / "config.alloy").read_text()
    label_blocks = re.findall(r"stage\.labels\s*\{(.*?)\}", alloy, flags=re.DOTALL)
    if len(label_blocks) != 1:
        fail("Alloy must expose exactly one reviewed label block")
    for forbidden in FORBIDDEN_LABELS:
        if re.search(rf"\b{re.escape(forbidden)}\s*=", label_blocks[0]):
            fail(f"forbidden Loki label: {forbidden}")
    if "loki.process" not in alloy or "otelcol.receiver.otlp" not in alloy:
        fail("Alloy log or trace pipeline is absent")


def validate_configs() -> None:
    required = [
        OBSERVABILITY / "prometheus" / "prometheus.yml",
        OBSERVABILITY / "loki" / "loki.yml",
        OBSERVABILITY / "tempo" / "tempo.yml",
        OBSERVABILITY / "grafana" / "provisioning" / "datasources" / "datasources.yml",
        OBSERVABILITY / "grafana" / "provisioning" / "dashboards" / "dashboards.yml",
        OBSERVABILITY / "compose.yaml",
        ROOT / "compose.yaml",
    ]
    for path in required:
        if not path.is_file() or not path.read_text().strip():
            fail(f"missing configuration: {path.relative_to(ROOT)}")
    compose = (ROOT / "compose.yaml").read_text()
    for profile in ("fixture", "radeon-local", "championship", "observability"):
        if profile not in compose:
            fail(f"compose profile missing: {profile}")
    for unsafe in ("0.0.0.0:3000:3000", "GF_AUTH_ANONYMOUS_ENABLED: \"true\""):
        if unsafe in compose:
            fail(f"unsafe observability default: {unsafe}")


def main() -> int:
    validate_dashboards()
    validate_alloy_labels()
    validate_configs()
    print("SignalForge observability bundle passed static validation")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
