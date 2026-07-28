"""
OmniKernel-ROCm — CLI entry point.

Usage:
    python -m src.main [OPTIONS]

Options:
    --codebase PATH     Path to the workload directory or script [default: .]
    --mock              Use mock tools (no real GPU required)
    --llm-url URL       Base URL for the local LLM server [default: http://localhost:8000/v1]
    --llm-model MODEL   Model name served by the LLM server
    --no-llm            Run in heuristic-only mode (no LLM)
    --db PATH           SQLite database path [default: omnikernel_memory.db]
"""

import argparse
import sys

from src.orchestrator import Orchestrator
from src.llm import LLMClient, LLMConfig, MockLLMClient

BANNER = r"""
  ___                 _ _  __                    _   ____  ___   ___ __  __
 / _ \ _ __ ___  _ _(_) |/ /___ _ __ _ __   ___| | |  _ \/ _ \ / __|  \/  |
| | | | '_ ` _ \| '_ \ | ' // _ \ '__| '_ \ / _ \ | | |_) | | | |   | |\/| |
| |_| | | | | | | | | | | . \  __/ |  | | | |  __/ | |  _ <| |_| |   | |  | |
 \___/|_| |_| |_|_| |_|_|_|\_\___|_|  |_| |_|\___|_| |_| \_\\___/ \___|_|  |_|

  Local ROCm/HIP Performance Diagnosis Agent
  AMD AI DevMaster Hackathon 2026
  Type 'quit' or 'exit' to end the session.
  Type 'help' for available commands.
"""

HELP_TEXT = """
Available commands during a session:
  <any description>      Describe your slow workload — agent will diagnose it
  "that's not right..."  Push back on the diagnosis — agent re-examines evidence
  "benchmark it"         Run a sandboxed benchmark to compare baseline vs proposed fix
  "apply the fix"        Save the proposed diff to a .patch file (requires approval)
  "reject"               Reject the proposed fix — nothing is applied
  "new session <path>"   Start a new session for a different codebase
  "history"              Show optimization history for this codebase
  "audit"                Show the action audit log for this session
  "help"                 Show this help text
  "quit" / "exit"        End the session
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OmniKernel-ROCm: Local ROCm/HIP Performance Diagnosis Agent"
    )
    parser.add_argument(
        "--codebase", default=".",
        help="Path to the workload directory or script (default: current directory)"
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="Use mock tools — no real GPU or ROCm installation required"
    )
    parser.add_argument(
        "--llm-url", default="http://localhost:8000/v1",
        help="Base URL of the local LLM inference server (vLLM or llama.cpp)"
    )
    parser.add_argument(
        "--llm-model", default="qwen2.5-coder-7b-instruct",
        help="Model name as registered in the LLM server"
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Disable LLM — run with heuristic-only diagnosis"
    )
    parser.add_argument(
        "--mock-llm", action="store_true",
        help="Use mock LLM client (deterministic canned responses for testing)"
    )
    parser.add_argument(
        "--db", default="omnikernel_memory.db",
        help="Path to the SQLite memory database"
    )
    return parser.parse_args()


def build_llm_client(args: argparse.Namespace):
    """Instantiate the appropriate LLM client based on flags."""
    if args.no_llm:
        return None
    if args.mock_llm or args.mock:
        return MockLLMClient()
    config = LLMConfig(
        base_url=args.llm_url,
        model=args.llm_model,
    )
    client = LLMClient(config=config)
    health = client.health_check()
    if health["status"] != "ok":
        print(f"[WARNING] LLM server not reachable: {health.get('error')}")
        print(f"          {health.get('hint', '')}")
        print("[WARNING] Falling back to heuristic-only mode.\n")
        return None
    print(f"[OmniKernel] LLM server connected. Model: {args.llm_model}")
    return client


def run_interactive_session(orch: Orchestrator) -> None:
    """Main REPL loop."""
    print(BANNER)
    orch.start_session()
    print(f"[OmniKernel] Codebase: {orch._codebase_path}")
    print(f"[OmniKernel] Mock mode: {orch.mock_tools}")
    print("-" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[OmniKernel] Session ended.")
            break

        if not user_input:
            continue

        lower = user_input.lower()

        if lower in ("quit", "exit", "q"):
            print("[OmniKernel] Session ended. Goodbye.")
            break

        if lower == "help":
            print(HELP_TEXT)
            continue

        if lower == "history":
            history = orch.memory.summarize_history(orch.session.codebase_fingerprint)
            print(f"\n{history}")
            continue

        if lower == "audit":
            log = orch.gate.get_audit_log()
            if not log:
                print("\nNo actions logged yet.")
            else:
                for entry in log:
                    print(f"  [{entry['timestamp']:.0f}] {entry['action_type']} → {entry['status']} ({entry['target']})")
            continue

        if lower.startswith("new session "):
            new_path = user_input[len("new session "):].strip()
            orch.start_session(new_path)
            print(f"[OmniKernel] New session started for: {new_path}")
            continue

        # Default: route through the orchestrator
        print("\nOmniKernel: thinking...\n")
        response = orch.handle_turn(user_input)
        print(f"OmniKernel:\n{response}")


def main() -> None:
    args = parse_args()
    llm_client = build_llm_client(args)

    orch = Orchestrator(
        codebase_path=args.codebase,
        llm_client=llm_client,
        mock_tools=args.mock,
        db_path=args.db,
    )

    run_interactive_session(orch)


if __name__ == "__main__":
    main()
