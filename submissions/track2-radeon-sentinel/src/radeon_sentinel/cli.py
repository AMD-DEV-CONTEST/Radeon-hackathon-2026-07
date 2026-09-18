"""Command-line demo entrypoint."""

import argparse
import json
from typing import Optional, Sequence

from .config import Settings
from .runtime import build_agent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a synthetic Radeon Sentinel investigation"
    )
    parser.add_argument(
        "--incident",
        default="api_latency",
        help="Incident fixture name or JSON path",
    )
    parser.add_argument(
        "--query",
        help="Investigation request; defaults to the fixture prompt",
    )
    parser.add_argument("--case-id", help="Reuse a local case memory ID")
    parser.add_argument(
        "--approve-remediation",
        action="store_true",
        help="Approve the simulated restart for this run",
    )
    parser.add_argument(
        "--no-remediation",
        action="store_true",
        help="Do not request the simulated restart",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete response as JSON",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    agent = build_agent(settings, args.incident)
    try:
        query = args.query or agent.environment.prompt
        response = agent.investigate(
            query=query,
            case_id=args.case_id,
            request_remediation=not args.no_remediation,
            approve_remediation=args.approve_remediation,
        )
        if args.json:
            print(
                json.dumps(
                    response.to_dict(),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            _print_human(response.to_dict())
    finally:
        agent.close()


def _print_human(response: dict) -> None:
    print(f"Case: {response['case_id']}")
    print(f"Status: {response['status']}")
    print(f"\nDiagnosis\n{response['summary']}")
    print("\nPlan")
    for step in response["plan"]:
        print(f"- [{step['status']}] {step['title']}")
    print("\nEvidence")
    for item in response["evidence"]:
        print(f"- {item['source']} ({item['score']:.4f})")
        print(f"  {item['excerpt']}")
    print("\nTools")
    for item in response["tool_results"]:
        print(f"- {item['name']}: {item['status']}")


if __name__ == "__main__":
    main()
