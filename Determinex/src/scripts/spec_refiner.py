#!/usr/bin/env python3
"""
spec_refiner.py — Oracle refinement with conversational response

Called by the refine_spec Tauri command when the user wants to modify a spec
and get an explanation back. Returns JSON: { response, spec }
"""

import argparse
import json
import sys
from pathlib import Path

import litellm

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

try:
    from scripts.hive.api_client import api_call, load_role_assignments
except ImportError:
    from hive.api_client import api_call, load_role_assignments

SYSTEM_PROMPT = """You are the Oracle for the Determinex Hive Mind — the AI advisor that helps users refine their software specifications before the build pipeline begins.

You speak directly to the user like a senior architect would: clear, practical, and honest about tradeoffs. You understand Rust, Go, and Python deeply. You know when a request adds scope creep, when it's a best practice, and when there are hidden gotchas.

When responding to a refinement request or question, you MUST use EXACTLY this format — no text before ORACLE_RESPONSE:, no text after the spec:

ORACLE_RESPONSE:
[Write 3-5 sentences total, structured like this:
1. Confirm exactly what you changed (or answer the question directly if they asked one).
2. Explain the key architectural implication or tradeoff this introduces — be concrete and specific, not generic.
3. Flag any hidden complexity or gotcha they should know before building this.
4. Suggest one specific thing they should consider refining next, based on what's in their spec.]

SPEC:
[The complete updated Determinex MD specification, all sections, starting with # Project Title. If the user only asked a question without requesting changes, repeat the spec unchanged.]"""


def refine_spec(current_spec: str, request: str) -> dict:
    roles = load_role_assignments()
    oracle_model = roles.get("oracle", "openai/gpt-4o")

    response = api_call(
        litellm.completion,
        model=oracle_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"CURRENT SPECIFICATION:\n\n{current_spec}\n\n"
                    f"USER REQUEST:\n{request}\n\n"
                    "Respond in the required ORACLE_RESPONSE / SPEC format:"
                ),
            },
        ],
        temperature=0.3,
        estimated_tokens=1400,
    )

    raw = response.choices[0].message.content.strip()

    if "ORACLE_RESPONSE:" in raw and "SPEC:" in raw:
        parts = raw.split("SPEC:", 1)
        oracle_part = parts[0].replace("ORACLE_RESPONSE:", "").strip()
        spec_part = parts[1].strip()
    else:
        # Fallback: treat full output as spec, generate generic response
        spec_part = raw
        oracle_part = "Spec updated based on your request."

    return {"response": oracle_part, "spec": spec_part}


def main():
    parser = argparse.ArgumentParser(description="Refine a Determinex spec with Oracle response.")
    parser.add_argument("--spec", help="Current specification text")
    parser.add_argument("--request", help="User's refinement request")
    parser.add_argument("--stdin", action="store_true", help="Read JSON payload from stdin")
    args = parser.parse_args()

    # Accept payload via stdin (JSON: {"spec": "...", "request": "..."}) to avoid
    # Windows 32767-char CLI arg limit when spec + conversation history are large.
    if args.stdin or not (args.spec and args.request):
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw)
            spec_text = payload.get("spec", "")
            request_text = payload.get("request", "")
        except Exception:
            print(json.dumps({"error": "Failed to parse stdin JSON"}), file=sys.stderr)
            sys.exit(1)
    else:
        spec_text = args.spec
        request_text = args.request

    if not spec_text or not request_text:
        print(json.dumps({"error": "spec and request are required"}), file=sys.stderr)
        sys.exit(1)

    try:
        result = refine_spec(spec_text, request_text)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
