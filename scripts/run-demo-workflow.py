#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "checkout-latency.json"


def request_json(base_url: str, method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def heading(text: str) -> None:
    print(f"\n\033[1;36m{text}\033[0m", flush=True)


def hold(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the complete Local Incident Commander demo workflow")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--pause", type=float, default=1.5, help="Pause between visible demo stages")
    args = parser.parse_args()

    run_id = uuid4().hex[:10]
    health = request_json(args.base_url, "GET", "/api/health")
    heading("PRIVATE RADEON SESSION")
    print(f"mode={health['mode']}  model={health['model']}  engine={health['engine']}")
    if health["mode"] != "local-radeon":
        raise SystemExit("Refusing to record: /api/health is not verified local-radeon mode")
    print("core inference endpoint=127.0.0.1  remote core requests=0")
    hold(args.pause)

    incident = json.loads(SAMPLE.read_text(encoding="utf-8"))
    response = request_json(
        args.base_url,
        "POST",
        "/api/investigations",
        {"request_id": f"demo-{run_id}-create", "incident": incident},
    )
    investigation = response["investigation"]
    heading("FOUR-STEP BOUNDED PLAN")
    for step in investigation["plan"]:
        tool = f" [{step['tool']}]" if step.get("tool") else ""
        print(f"{step['order']}. {step['goal']}{tool}")
    hold(args.pause)

    for index in range(4):
        response = request_json(
            args.base_url,
            "POST",
            f"/api/investigations/{investigation['id']}/next",
            {"request_id": f"demo-{run_id}-next-{index + 1}", "expected_version": investigation["version"]},
        )
        investigation = response["investigation"]
        event = investigation["trace"][-1]
        title = event.get("tool") or "synthesize_root_cause"
        heading(f"STEP {index + 1}/4  {title}")
        print(f"status={event['status']}  duration_ms={event.get('duration_ms', 0)}")
        if event.get("evidence_ids"):
            print("evidence=" + ", ".join(event["evidence_ids"]))
        print(event["summary"])
        hold(args.pause)

    heading("EVIDENCE-GROUNDED RCA")
    top = investigation["hypotheses"][0]
    print(f"root_cause={top['title']}  confidence={top['confidence']:.0%}")
    print("citations=" + ", ".join(top["evidence_ids"]))
    print(investigation["executive_summary"])
    hold(args.pause)

    decisions = ((investigation["proposed_actions"][0], "approved"), (investigation["proposed_actions"][1], "rejected"))
    heading("HUMAN APPROVAL GATE / SIMULATION ONLY")
    for action, decision in decisions:
        response = request_json(
            args.base_url,
            "POST",
            f"/api/investigations/{investigation['id']}/actions/{action['id']}/decision",
            {
                "request_id": f"demo-{run_id}-{decision}",
                "expected_version": investigation["version"],
                "decision": decision,
                "comment": "Recorded demo decision; no production command executed.",
            },
        )
        investigation = response["investigation"]
        print(f"{decision.upper():8} {action['command_preview']}")
        hold(args.pause)

    question = "Why should we reject the connection-pool increase?"
    response = request_json(
        args.base_url,
        "POST",
        f"/api/investigations/{investigation['id']}/messages",
        {
            "request_id": f"demo-{run_id}-follow-up",
            "expected_version": investigation["version"],
            "content": question,
        },
    )
    investigation = response["investigation"]
    answer = investigation["messages"][-1]
    heading("SESSION MEMORY / CITED FOLLOW-UP")
    print("operator: " + question)
    print("agent: " + answer["content"])
    print("citations=" + ", ".join(answer["evidence_ids"]))
    print("\nDemo complete: no production action was executed.", flush=True)


if __name__ == "__main__":
    main()
