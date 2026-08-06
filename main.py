"""CodeRisk Agent - AI Code Quality & Risk Analyzer

Usage:
    code-risk analyze <path>   Analyze code files/directory
    code-risk demo             Run demo analysis
    code-risk info             Show configuration

Options:
    --no-ai                    Disable LLM semantic analysis
    --semgrep-config <rules>   Semgrep rules (default: p/default)
    --output <format>          Output format: terminal|json|md|sarif|all (default: terminal)
    --custom-rules <dir>       Load custom rules from JSON directory
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from core.models import AnalysisRequest, CodeFile, Language

console = Console()

BANNER = r"""[bold cyan]
 ██████╗ ██████╗ ██████╗ ███████╗    ██████╗ ██╗███████╗██╗  ██╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝    ██╔══██╗██║██╔════╝██║ ██╔╝
██║     ██║   ██║██║  ██║█████╗      ██████╔╝██║███████╗█████╔╝
██║     ██║   ██║██║  ██║██╔══╝      ██╔══██╗██║╚════██║██╔═██╗
╚██████╗╚██████╔╝██████╔╝███████╗    ██║  ██║██║███████║██║  ██╗
 ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝    ╚═╝  ╚═╝╚═╝╚══════╝╚═╝  ╚═╝
[/]"""

VERSION = "1.0"

SUPPORTED_EXTENSIONS = {".c", ".h", ".py"}


def collect_files(path: Path) -> list[CodeFile]:
    """Collect supported code files from a path."""
    files: list[CodeFile] = []
    if path.is_file():
        if path.suffix in SUPPORTED_EXTENSIONS:
            files.append(CodeFile.from_path(path))
    else:
        for ext in SUPPORTED_EXTENSIONS:
            for f in path.rglob(f"*{ext}"):
                if f.is_file():
                    files.append(CodeFile.from_path(f))
    return files


def cmd_analyze(
    path_str: str,
    enable_ai: bool = True,
    semgrep_config: str = "p/default",
    output_format: str = "terminal",
    custom_rules_dir: str | None = None,
) -> None:
    """Analyze code files or directory using the Orchestrator pipeline."""
    path = Path(path_str)

    if not path.exists():
        console.print(f"[red]Path not found: {path}[/]")
        sys.exit(1)

    files = collect_files(path)
    if not files:
        console.print(
            f"[yellow]No supported code files found ({', '.join(SUPPORTED_EXTENSIONS)})[/]"
        )
        sys.exit(0)

    # Load custom rules if specified
    custom_rules = []
    if custom_rules_dir:
        custom_rules_path = Path(custom_rules_dir)
        if custom_rules_path.is_dir():
            for rule_file in custom_rules_path.glob("*.json"):
                try:
                    import json
                    with open(rule_file) as rf:
                        rule = json.load(rf)
                        if isinstance(rule, dict):
                            custom_rules.append(rule)
                        elif isinstance(rule, list):
                            custom_rules.extend(rule)
                except Exception as e:
                    console.print(f"[yellow]Failed to load custom rule {rule_file}: {e}[/]")
            console.print(f"[cyan]Loaded {len(custom_rules)} custom rules from {custom_rules_dir}[/]")
        else:
            console.print(f"[yellow]Custom rules directory not found: {custom_rules_dir}[/]")

    # Build request
    request = AnalysisRequest(
        files=files,
        rules=[semgrep_config],
        enable_ai=enable_ai,
        custom_rules=custom_rules,
    )

    # Initialize Orchestrator
    from orchestrator import Orchestrator

    llm = None
    if enable_ai:
        try:
            from core.llm_client import LLMClient
            llm = LLMClient()
        except Exception as e:
            console.print(f"[yellow]LLM init failed, running without AI: {e}[/]")

    orchestrator = Orchestrator(llm_client=llm, custom_rules=request.custom_rules)
    orchestrator.run(request, output_format=output_format)


def cmd_demo() -> None:
    """Run demo analysis on sample vulnerable code."""
    from orchestrator import Orchestrator

    console.print("[bold cyan]CodeRisk Agent Demo[/]\n")

    demo_c = CodeFile(
        path=Path("demo/vulnerable.c"),
        content="""#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int login(char *input) {
    char password[32];
    strcpy(password, input);
    if (strcmp(password, "admin123") == 0) {
        printf("Welcome!\\n");
        system("echo logged in");
        return 1;
    }
    return 0;
}

void process() {
    char *buf = malloc(256);
    gets(buf);
    printf(buf);
    free(buf);
    free(buf);
}
""",
        language=Language.C,
    )

    demo_py = CodeFile(
        path=Path("demo/server.py"),
        content="""import os
import pickle
from flask import request

@app.route("/run")
def run_cmd():
    cmd = request.args.get("cmd")
    return os.system(cmd)

@app.route("/load")
def load_data():
    data = request.get_data()
    return pickle.loads(data)

@app.route("/calc")
def calculate():
    expr = request.args.get("expr")
    return str(eval(expr))
""",
        language=Language.PYTHON,
    )

    request = AnalysisRequest(
        files=[demo_c, demo_py],
        enable_ai=False,  # Demo mode: no LLM, fast
    )

    orchestrator = Orchestrator()  # No LLM for demo
    orchestrator.run(request)


def cmd_info() -> None:
    """Show configuration info."""
    import os

    from rich.table import Table

    table = Table(title="CodeRisk Agent Config", show_header=True)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Version", VERSION)
    table.add_row("Default Model", "Qwen2.5-Coder-32B-Instruct")
    table.add_row("Backends", "llama-server + llama-cpp-python (local only)")
    table.add_row("Analyzers", "Static (regex) + Semgrep + LLM semantic + Deep verifier")
    table.add_row("Languages", "C (.c/.h) + Python (.py)")
    table.add_row("CWE Rules", "CWE-120/134/476/415/78/95/502/73/617/89")
    table.add_row("Pipeline", "Orchestrator -> 4 Agents -> Report")

    # Read actual env config
    backend = os.getenv("LLM_BACKEND", "local_llama_cpp")
    table.add_row("Active Backend", backend)

    console.print(table)


def main():
    console.print(BANNER)

    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        console.print(__doc__)
        return

    cmd = args[0]

    if cmd == "analyze":
        if len(args) < 2:
            console.print("[red]Usage: code-risk analyze <path>[/]")
            sys.exit(1)
        enable_ai = "--no-ai" not in args
        semgrep_config = "p/default"
        output_format = "terminal"
        if "--semgrep-config" in args:
            idx = args.index("--semgrep-config")
            if idx + 1 < len(args):
                semgrep_config = args[idx + 1]
        custom_rules_dir = None
        if "--custom-rules" in args:
            idx = args.index("--custom-rules")
            if idx + 1 < len(args):
                custom_rules_dir = args[idx + 1]
        if "--output" in args:
            idx = args.index("--output")
            if idx + 1 < len(args):
                output_format = args[idx + 1]
        cmd_analyze(
            args[1],
            enable_ai=enable_ai,
            semgrep_config=semgrep_config,
            output_format=output_format,
            custom_rules_dir=custom_rules_dir,
        )
    elif cmd == "demo":
        cmd_demo()
    elif cmd == "info":
        cmd_info()
    else:
        console.print(f"[red]Unknown command: {cmd}[/]")
        console.print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
