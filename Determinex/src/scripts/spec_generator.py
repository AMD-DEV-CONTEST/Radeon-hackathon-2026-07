#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys

os.environ.setdefault("LITELLM_TELEMETRY", "False")
os.environ.setdefault("LITELLM_LOG", "ERROR")

import litellm

# Add repo + scripts paths so both `scripts.hive.*` and legacy `hive.*`
# imports work whether this file is executed or imported in tests.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
for _path in (_REPO_ROOT, _SCRIPT_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)
try:
    from scripts.hive.api_client import api_call, load_role_assignments
except ImportError:
    # Fallback if pathing is slightly different
    from hive.api_client import api_call, load_role_assignments


class UserFacingSpecError(RuntimeError):
    """Expected setup/runtime failure safe to show in the IDE."""


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_litellm_config() -> dict:
    config_path = os.path.join(_project_root(), "litellm_config.yaml")
    if not os.path.exists(config_path):
        return {}
    try:
        import yaml

        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _alias_map(config: dict) -> dict[str, dict]:
    aliases: dict[str, dict] = {}
    for entry in config.get("model_list", []) or []:
        name = str(entry.get("model_name", "")).strip()
        params = entry.get("litellm_params") or {}
        if name and params.get("model"):
            aliases[name] = params
    return aliases


def _resolve_alias(alias: str, aliases: dict[str, dict]) -> str:
    params = aliases.get(alias) or {}
    return str(params.get("model") or alias).strip()


def _ollama_tag(model: str) -> str | None:
    if not model.startswith("ollama/"):
        return None
    return model.removeprefix("ollama/").strip()


def _ollama_models() -> tuple[list[str], str | None]:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return [], str(exc)

    if result.returncode != 0:
        return [], (result.stderr or result.stdout or "ollama list failed").strip()

    tags: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            tags.append(parts[0])
    return tags, None


def _tag_installed(required: str, installed: list[str]) -> bool:
    return any(
        tag == required or tag.startswith(f"{required}:") or tag.startswith(required)
        for tag in installed
    )


def _canonical_installed_tag(required: str, installed: list[str]) -> str | None:
    for tag in installed:
        if tag == required:
            return tag
    for tag in installed:
        if tag.startswith(f"{required}:") or tag.startswith(required):
            return tag
    return None


def _router_fallbacks(config: dict, alias: str) -> list[str]:
    rows = (config.get("router_settings") or {}).get("fallbacks") or []
    for row in rows:
        if isinstance(row, dict) and alias in row:
            values = row.get(alias) or []
            if isinstance(values, list):
                return [str(value).strip() for value in values if str(value).strip()]
    return []


def _candidate_aliases(primary: str, roles: dict, config: dict) -> list[str]:
    candidates = [
        primary,
        *(_router_fallbacks(config, primary)),
        str(roles.get("architect") or "").strip(),
        *(_router_fallbacks(config, str(roles.get("architect") or "").strip())),
        "local/fast",
        "determinex/observer",
        "local/coder",
        "determinex/engineer",
    ]
    unique: list[str] = []
    for alias in candidates:
        if alias and alias not in unique:
            unique.append(alias)
    return unique


def select_spec_model(roles: dict) -> str:
    """Pick a spec-generation model that actually exists in local Ollama.

    Spec generation runs before a Hive session exists, so it needs its own
    health preflight. The executor already preflights Builder; this prevents
    the intake UI from failing later with raw LiteLLM/Ollama stderr.
    """
    primary = str(roles.get("oracle") or roles.get("architect") or "local/fast").strip()
    config = _load_litellm_config()
    aliases = _alias_map(config)
    installed, ollama_error = _ollama_models()

    primary_model = _resolve_alias(primary, aliases)
    primary_tag = _ollama_tag(primary_model)
    if primary_tag and installed:
        canonical = _canonical_installed_tag(primary_tag, installed)
        if canonical:
            return primary if canonical == primary_tag else f"ollama/{canonical}"

    for alias in _candidate_aliases(primary, roles, config):
        model = _resolve_alias(alias, aliases)
        tag = _ollama_tag(model)
        canonical = _canonical_installed_tag(tag, installed) if tag and installed else None
        if tag and canonical:
            if alias != primary:
                print(
                    f"[SPEC] Switched spec model from {primary} to {alias} because {primary_tag or primary_model} is unavailable.",
                    file=sys.stderr,
                )
            return alias if canonical == tag else f"ollama/{canonical}"

    if primary_tag:
        if ollama_error:
            raise UserFacingSpecError(
                "Ollama is not reachable, so Determinex cannot generate the spec yet. "
                "Start Ollama or open Settings -> Models and run the model check."
            )
        have = ", ".join(installed[:8]) if installed else "no local models reported"
        raise UserFacingSpecError(
            f"The selected spec model is not installed in Ollama: {primary_tag}. "
            f"Installed models: {have}. Open Settings -> Models to repair models, "
            f"or run `ollama pull {primary_tag}`."
        )

    return primary


SYSTEM_PROMPT = """You are the Oracle for the Determinex Hive Mind.
Your task is to convert free-text project ideas into the exact Determinex MD Specification format.

Output MUST follow this EXACT valid markdown template. Fill in the appropriate details based on the user's prompt. Do NOT add preamble or summary text. Output ONLY the markdown spec.

# [Project Title]

## Goal
[One paragraph describing what it does, not how it does it]

## Language
[Output exactly one of: rust, go, python, typescript]

## Project Type
[For rust: library, cli-tool, api-service, daemon. For go: cli-tool, api-service, grpc-service, library. For python: script, cli-tool, api-service, package, data-pipeline. For typescript: web-app, mobile-app, fullstack-app, api-service, package]

## Constraints
- [Compile-time or design rule]
- [e.g. no global state, must be threadsafe using Arc<Mutex<T>>, etc.]

## Files
- `[File path]` — [Purpose of the file]

## Dependencies
- [Name] — [Reason]

## Tests
[Description of basic functional tests]

## Notes
[Any architectural guidelines or specific algorithm constraints]

Selection rules:
- If the user asks for a website, web app, dashboard, portal, SaaS, frontend, or mobile application, prefer Language: typescript.
- If the user asks for both website/web and mobile apps, use Project Type: fullstack-app and include web, mobile, shared API, and tests in Files.
- Use cli-tool only when the user explicitly asks for CLI, command-line, terminal, shell, or console behavior.
- Do not convert web/mobile product requests into Rust CLI tools.
"""


def generate_spec_from_idea(idea: str):
    roles = load_role_assignments()
    oracle_model = select_spec_model(roles)

    response = api_call(
        litellm.completion,
        model=oracle_model,
        role="oracle",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"USER IDEA:\n\n{idea}\n\nGenerate the MD Spec format now:",
            },
        ],
        temperature=0.2,
        estimated_tokens=800,
    )
    return response.choices[0].message.content


def main():
    import json

    parser = argparse.ArgumentParser(description="Generate Determinex MD Spec from free text.")
    parser.add_argument("--idea", type=str, required=False, help="The free text idea prompt")
    parser.add_argument(
        "--stdin", action="store_true", help='Read idea as JSON from stdin ({"idea": "..."})'
    )
    args = parser.parse_args()

    if args.stdin:
        data = json.loads(sys.stdin.read())
        idea = data.get("idea", "")
    elif args.idea:
        idea = args.idea
    else:
        print("ERROR: --idea or --stdin required", file=sys.stderr)
        sys.exit(1)

    try:
        spec = generate_spec_from_idea(idea)
        print(spec)
    except UserFacingSpecError as e:
        print(f"USER_ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
