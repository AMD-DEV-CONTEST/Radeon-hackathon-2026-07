#!/usr/bin/env python3
"""LLM-assisted per-tool override generator.

Workflow for each tool:
  1. Load tool's action sheet (failing tests + sample assertions)
  2. Read the tool's golden/help text + test names from PB metadata
  3. Build a single LLM prompt with:
       - Tool name + description
       - Expected CLI behavior (from frontier_pct comparison, test name patterns)
       - Top 5 failing test names + their expected outputs (from assertion messages)
       - Current scaffold's main.py (so the LLM knows the baseline)
  4. Send to Anthropic Claude API (Opus 4.7 or Sonnet 4.6)
  5. Extract returned main.py from the response
  6. Write to corpus/programbench/per_tool_overrides/<tool>/main.py
  7. Run apply_overrides_to_scaffolds.py to push into factory dir
  8. Eval against Hetzner or locally

This script handles the prompt-building + API call + extraction.
Calling code orchestrates which tools to run.

Usage:
  python scripts/analysis/llm_gen_override.py --tool burntsushi__ripgrep.3b7fd44
  python scripts/analysis/llm_gen_override.py --tier mid       # all mid-tier tools
  python scripts/analysis/llm_gen_override.py --slugs csview,shellharden

Requires: ANTHROPIC_API_KEY in env.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = Path("T:/determinex-programbench")
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"
ACTION_SHEETS = ROOT / "corpus" / "programbench" / "results" / "action_sheets"
PER_TOOL_FAIL = Path("c:/tmp/per_tool_failures.json")
SNIPPET_REG = ROOT / "corpus" / "programbench" / "_snippets" / "registry.json"
PB_TASKS = Path("c:/tmp/pb_tasks_200.tsv")


PROMPT_TEMPLATE = """You are implementing a Python CLI tool that must pass a specific set of behavioral tests.

# Tool: {tool_name}
- Language hint: {language}
- Total tests: {total}
- Currently passing: {passed} (= {pct:.2f}%)
- Failing: {failed} tests below

# Failing test patterns

{failures_block}

# Current main.py (baseline — needs replacement)

```python
{current_main_py}
```

# Snippets from successful tools (you may reuse patterns)

{snippets_block}

# Your task

Write a complete, working `main.py` that passes as many of the failing tests as possible while keeping all currently-passing tests passing. The script:

1. Must be self-contained Python 3 (no external deps beyond stdlib).
2. Must handle `sys.argv` directly (the eval system invokes the script as an executable).
3. Must implement actual tool behavior, not just stubs — use the expected outputs from failing-test assertions as the spec.
4. Must produce byte-exact output matching the assertion expectations.
5. Must handle SIGPIPE, BrokenPipeError, KeyboardInterrupt gracefully.
6. Must handle `--help`/`-h` (rc=0), `--version`/`-V` (rc=0), no-args (rc=2 with usage to stderr).

Return ONLY the contents of the `main.py` file, wrapped in a single ```python ... ``` fenced code block. No commentary before or after.
"""


def load_pb_meta() -> dict:
    meta = {}
    with PB_TASKS.open(encoding="utf-8") as f:
        next(f)
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 6:
                _, inst, lang, _, tests, frontier = parts[:6]
                slug = inst.lower().replace("/", "__")
                meta[slug] = {
                    "lang": lang,
                    "tests": int(tests),
                    "tool_name": inst.split("/", 1)[-1].lower(),
                    "frontier_pct": float(frontier),
                }
    return meta


def load_failures() -> dict:
    return json.loads(PER_TOOL_FAIL.read_text(encoding="utf-8"))


def load_snippets() -> dict:
    try:
        return json.loads(SNIPPET_REG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_action_sheet(tool_key: str) -> str:
    p = ACTION_SHEETS / f"{tool_key}.md"
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return ""


def find_scaffold_main(tool_key: str) -> str:
    """Read current scaffold's main.py for context."""
    candidates = [
        EVAL_ROOT / f"determinex_pb_factory_{tool_key}_v1" / tool_key / "source" / "main.py",
    ]
    for c in candidates:
        if c.is_file():
            return c.read_text(encoding="utf-8")
    return "(no current main.py found)"


def build_failures_block(fail_data: dict) -> str:
    """Render a markdown block describing top failing tests + samples."""
    lines = []
    for first_line, count in fail_data.get("top_first_lines", [])[:8]:
        lines.append(f"- ({count}x) `{first_line[:200]}`")
    if fail_data.get("bucket_samples"):
        lines.append("")
        lines.append("Test name samples per bucket:")
        for bucket, samples in fail_data.get("bucket_samples", {}).items():
            lines.append(f"- `{bucket}`:")
            for s in samples[:3]:
                lines.append(f"  - `{s}`")
    return "\n".join(lines) or "(no failure data)"


def build_snippets_block(snippets: dict, lang: str) -> str:
    """Render top snippet patterns matching the tool's language."""
    if not snippets:
        return "(no snippet registry available)"
    lines = []
    for bucket, sources in snippets.get("buckets", {}).items():
        same_lang = [s for s in sources if s.get("lang") == lang]
        if same_lang:
            best = max(same_lang, key=lambda s: s.get("our_pct", 0))
            lines.append(f"- `{bucket}` (e.g. {best['tool']} at {best['our_pct']}%)")
    return "\n".join(lines[:10]) or "(no matching snippets)"


def build_prompt(tool_key: str, meta: dict, fail_data: dict, snippets: dict) -> str:
    slug = tool_key.rsplit(".", 1)[0] if "." in tool_key else tool_key
    m = meta.get(slug, {})
    return PROMPT_TEMPLATE.format(
        tool_name=m.get("tool_name", slug),
        language=m.get("lang", "?"),
        total=fail_data.get("total", 0),
        passed=fail_data.get("passed", 0),
        failed=fail_data.get("failed", 0),
        pct=fail_data.get("pct", 0.0),
        failures_block=build_failures_block(fail_data),
        current_main_py=find_scaffold_main(tool_key)[:6000],
        snippets_block=build_snippets_block(snippets, m.get("lang", "")),
    )


def extract_python_from_response(response_text: str) -> str | None:
    """Find the python code block in the LLM response AND validate it parses.

    Handles multiple model output styles. CRITICAL: rejects code that
    fails `compile()` — never ships syntactically broken Python.
    """
    candidates = []
    # 1. Strict python fence
    for pat in (r"```python\r?\n(.*?)```", r"```py\r?\n(.*?)```", r"```python3?\r?\n(.*?)```"):
        m = re.search(pat, response_text, re.DOTALL | re.IGNORECASE)
        if m:
            candidates.append(m.group(1).rstrip())
    # 2. Bare fence
    m = re.search(r"```\r?\n(.*?)```", response_text, re.DOTALL)
    if m:
        body = m.group(1).rstrip()
        if any(
            t in body for t in ("import ", "def ", "#!/usr/bin/env python", "sys.exit", "print(")
        ):
            candidates.append(body)
    # 3. No fence; starts with shebang
    body = response_text.lstrip()
    if body.startswith("#!/usr/bin/env python") or body.startswith("#!"):
        candidates.append(body)
    # 4. Anchor-based
    for anchor in ("#!/usr/bin/env python", "import sys", "from __future__", "def main"):
        idx = response_text.find(anchor)
        if idx >= 0:
            candidates.append(response_text[idx:].rstrip())
            break

    # Validate: must parse (compile to AST without SyntaxError)
    for code in candidates:
        if not code or len(code) < 200:
            continue
        try:
            compile(code, "<llm-response>", "exec")
            return code
        except SyntaxError as e:
            # Log and try next candidate
            print(f"    [extract] candidate rejected (syntax error line {e.lineno}: {e.msg[:60]})")
            continue
    return None


def call_anthropic(prompt: str, model: str = "claude-opus-4-7") -> str:
    """Send prompt to Anthropic API and return response text."""
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package not installed. Run: pip install anthropic")
        sys.exit(1)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text  # type: ignore


def call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
    """DeepSeek API call. Cheap (~$0.001/tool). OpenAI-compatible."""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY not set")
        sys.exit(1)
    import urllib.error
    import urllib.request

    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8000,
            "temperature": 0.2,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.loads(r.read())
        return j["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        print(f"DeepSeek HTTP error: {e.code} {e.read()[:200]}")
        raise


def call_ollama(prompt: str, model: str = "qwen2.5-coder:7b") -> str:
    """Ollama call. Honors OLLAMA_HOST env var (default localhost:11434).
    For Hetzner: export OLLAMA_HOST=http://5.78.192.163:11434
    """
    import urllib.request

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    if not host.startswith("http"):
        host = f"http://{host}"
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 8000, "temperature": 0.2},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        j = json.loads(r.read())
    return j.get("response", "")


# Fallback chain: try each (backend, model) in order until extractable code returned.
FALLBACK_CHAIN = [
    ("ollama", "qwen2.5-coder:7b"),  # Hetzner-hosted, FREE
    ("deepseek", "deepseek-chat"),  # Cheap (~$0.001/call)
    ("anthropic", "claude-sonnet-4-6"),  # Medium (~$0.01)
    ("anthropic", "claude-opus-4-7"),  # Expensive (~$0.05) last
]


def call_with_fallback(
    prompt: str, chain: list[tuple[str, str]] | None = None
) -> tuple[str, str, str]:
    """Try backends in fallback order. Returns (backend, model, response) of first
    that returns extractable code. Raises if all fail."""
    chain = chain or FALLBACK_CHAIN
    last_err = None
    for backend, model in chain:
        try:
            resp = call_llm(prompt, backend, model)
            code = extract_python_from_response(resp)
            if code and len(code) > 200:  # arbitrary minimum
                return (backend, model, resp)
            last_err = f"{backend}/{model}: no extractable code"
        except Exception as e:
            last_err = f"{backend}/{model}: {e}"
            print(f"    fallback skipping {backend}/{model}: {e}")
            continue
    raise RuntimeError(f"all fallback backends failed; last: {last_err}")


def call_llm(prompt: str, backend: str, model: str) -> str:
    if backend == "anthropic":
        return call_anthropic(prompt, model)
    if backend == "deepseek":
        return call_deepseek(prompt, model)
    if backend == "ollama":
        return call_ollama(prompt, model)
    raise ValueError(f"unknown backend: {backend}")


def generate_override(
    tool_key: str,
    meta: dict,
    failures: dict,
    snippets: dict,
    model: str = "deepseek-chat",
    backend: str = "deepseek",
    use_fallback: bool = False,
    dry_run: bool = False,
) -> bool:
    fail_data = failures.get(tool_key)
    if not fail_data:
        print(f"  {tool_key}: no failure data — skip")
        return False
    if fail_data.get("pct", 0) >= 100:
        print(f"  {tool_key}: already LOCKED — skip")
        return False

    prompt = build_prompt(tool_key, meta, fail_data, snippets)

    if dry_run:
        print(f"  {tool_key}: dry-run, prompt length = {len(prompt)} chars")
        return True

    if use_fallback:
        print(f"  {tool_key}: fallback chain (prompt {len(prompt)} chars)")
        try:
            backend, model, response = call_with_fallback(prompt)
            print(f"    landed on: {backend}/{model}")
        except Exception as e:
            print(f"  {tool_key}: all fallbacks failed: {e}")
            return False
    else:
        print(f"  {tool_key}: calling {backend}/{model} (prompt {len(prompt)} chars)")
        try:
            response = call_llm(prompt, backend=backend, model=model)
        except Exception as e:
            print(f"  {tool_key}: API call failed: {e}")
            return False

    main_py = extract_python_from_response(response)
    if not main_py:
        print(f"  {tool_key}: response had no python block")
        return False

    target_dir = OVERRIDES_DIR / tool_key
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "main.py"
    target.write_text(main_py, encoding="utf-8", newline="\n")
    print(f"  {tool_key}: wrote {len(main_py)} chars to {target}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", help="single tool_key (e.g. wfxr__csview.8ac4de0)")
    ap.add_argument("--slugs", help="comma-separated tool slug filter substring")
    ap.add_argument(
        "--tier",
        choices=["near-lock", "upper", "mid", "floor", "all-below-lock"],
        help="generate for entire tier",
    )
    ap.add_argument(
        "--backend",
        default="deepseek",
        choices=["anthropic", "deepseek", "ollama"],
        help="LLM backend (ignored if --use-fallback)",
    )
    ap.add_argument("--model", default=None, help="model id; defaults by backend")
    ap.add_argument(
        "--use-fallback", action="store_true", help="try Qwen->DeepSeek->Sonnet->Opus in order"
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if not args.model:
        args.model = {
            "anthropic": "claude-opus-4-7",
            "deepseek": "deepseek-chat",
            "ollama": "determinex-engineer-v11-dsl",
        }[args.backend]

    meta = load_pb_meta()
    failures = load_failures()
    snippets = load_snippets()

    candidates = []
    if args.tool:
        candidates = [args.tool]
    elif args.slugs:
        substrs = [s.strip() for s in args.slugs.split(",") if s.strip()]
        for tk in failures.keys():
            if any(s in tk for s in substrs):
                candidates.append(tk)
    elif args.tier:
        tier_ranges = {
            "near-lock": (95.0, 99.99),
            "upper": (70.0, 94.99),
            "mid": (30.0, 69.99),
            "floor": (0.01, 29.99),
            "all-below-lock": (0.01, 99.99),
        }
        lo, hi = tier_ranges[args.tier]
        for tk, d in failures.items():
            pct = d.get("pct", 0)
            if lo <= pct <= hi:
                candidates.append(tk)
        # Sort by pct descending (work closest-to-lock first)
        candidates.sort(key=lambda tk: -failures[tk].get("pct", 0))
    else:
        print("Must specify --tool, --slugs, or --tier")
        sys.exit(1)

    if args.limit:
        candidates = candidates[: args.limit]

    mode = (
        "fallback-chain (Qwen/Hetzner -> DeepSeek -> Sonnet -> Opus)"
        if args.use_fallback
        else f"{args.backend}/{args.model}"
    )
    print(f"Generating overrides for {len(candidates)} tool(s) using {mode}")
    success = 0
    for tk in candidates:
        if generate_override(
            tk,
            meta,
            failures,
            snippets,
            model=args.model,
            backend=args.backend,
            use_fallback=args.use_fallback,
            dry_run=args.dry_run,
        ):
            success += 1
    print()
    print(f"Generated: {success}/{len(candidates)}")


if __name__ == "__main__":
    main()
