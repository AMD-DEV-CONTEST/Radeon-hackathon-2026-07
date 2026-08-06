"""Orchestrator: State Machine Pipeline

Manages the complete analysis flow through states:
INIT -> PARSE -> ANALYZE -> VERIFY -> REPORT -> DONE

Coordinates all 4 agents with memory layer, CVE client, and Semgrep.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from pathlib import Path
from typing import Optional

from rich.console import Console

from agents.deep_verifier import DeepVerifier
from agents.report_generator import ReportGenerator
from agents.semantic_analyzer import SemanticAnalyzer
from agents.static_analyzer import StaticAnalyzer
from core.cve_client import CVEClient
from core.llm_client import LLMClient
from core.memory import MemoryLayer
from core.taint_analyzer import TaintAnalyzer
from core.dependency_scanner import scan_project_dependencies
from core.models import (
    AnalysisRequest,
    AnalysisResult,
    CodeFile,
    Language,
    Risk,
)

console = Console()

MIN_LINES_FOR_LLM = 5
MAX_STATIC_WORKERS = 4   # CPU-bound parallelism
MAX_SEMANTIC_WORKERS = 1  # GPU-bound, limited concurrency (reduced from 2 to avoid VRAM contention)


class State(str, Enum):
    INIT = "init"
    PARSE = "parse"
    ANALYZE = "analyze"
    VERIFY = "verify"
    REPORT = "report"
    DONE = "done"
    ERROR = "error"


VALID_TRANSITIONS = {
    State.INIT: {State.PARSE, State.ERROR},
    State.PARSE: {State.ANALYZE, State.ERROR},
    State.ANALYZE: {State.VERIFY, State.ERROR},
    State.VERIFY: {State.REPORT, State.ERROR},
    State.REPORT: {State.DONE, State.ERROR},
}


class Orchestrator:
    """State machine orchestrator for the analysis pipeline."""

    def __init__(self, llm_client: Optional[LLMClient] = None, custom_rules: Optional[list] = None):
        self.state = State.INIT
        self.static_analyzer = StaticAnalyzer(custom_rules=custom_rules or [])
        self.llm = llm_client
        self.semantic_analyzer = SemanticAnalyzer(llm_client) if llm_client else None
        self.memory = MemoryLayer()
        self.cve = CVEClient()
        self.taint = TaintAnalyzer()
        self.verifier = DeepVerifier(
            llm_client=llm_client,
            memory=self.memory,
            cve_client=self.cve,
        )
        self.reporter = ReportGenerator()

    def run(
        self,
        request: AnalysisRequest,
        output_format: str = "terminal",
    ) -> AnalysisResult:
        """Run the complete analysis pipeline."""
        start_time = time.monotonic()
        perf_timings: dict[str, float] = {}  # Phase -> duration_ms

        # State: PARSE
        self.state = State.PARSE
        console.print(f"\n[bold cyan]Orchestrator: Analyzing {len(request.files)} files...[/]\n")

        valid_files = self._validate_files(request.files)
        if not valid_files:
            console.print("[yellow]No valid files to analyze.[/]")
            return AnalysisResult(
                request_id=f"scan-{int(time.time())}",
                files_analyzed=0,
                risks=[],
                analysis_time_ms=0,
                model_used="none",
            )

        # State: ANALYZE
        self.state = State.ANALYZE
        all_risks = []

        # Phase 1: Static analysis (PARALLEL — CPU-bound)
        t0 = time.monotonic()
        console.print("[bold]  Phase 1: Static analysis (Agent 1, parallel)[/]")
        with ThreadPoolExecutor(max_workers=MAX_STATIC_WORKERS) as pool:
            future_map = {pool.submit(self.static_analyzer.analyze, f): f for f in valid_files}
            for future in as_completed(future_map):
                f = future_map[future]
                try:
                    risks = future.result()
                    all_risks.extend(risks)
                    if risks:
                        console.print(f"  [red]  {f.path}: {len(risks)} risks[/]")
                    else:
                        console.print(f"  [green]  {f.path}: clean[/]")
                except Exception as e:
                    console.print(f"  [yellow]  {f.path}: error — {e}[/]")
        perf_timings['agent1_static'] = (time.monotonic() - t0) * 1000

        # Phase 1.5: Dependency scanning (smart root detection)
        t0 = time.monotonic()
        console.print("\n[bold]  Phase 1.5: Dependency scanning[/]")
        try:
            project_root = self._find_project_root(valid_files)
            console.print(f"  [dim]  Project root: {project_root}[/]")
            dep_findings = scan_project_dependencies(project_root)
            if dep_findings:
                console.print(f"  [red]  Dependencies: {len(dep_findings)} vulnerable packages[/]")
                for finding in dep_findings:
                    from core.models import Confidence, Evidence, Language, Risk, Severity
                    all_risks.append(Risk(
                        id=f"RISK-{len(all_risks)+1:03d}",
                        title=f"Vulnerable dep: {finding['package']} {finding['version']}",
                        description=finding['description'],
                        severity=Severity.HIGH,
                        confidence=Confidence.HIGH,
                        cwe_id=finding['cwe'],
                        language=Language.UNKNOWN,
                        file_path=Path(finding.get('file', 'requirements.txt')),
                        line_start=0,
                        line_end=0,
                        evidence=[Evidence(
                            source="dependency_scan",
                            snippet=f"{finding['package']}=={finding['version']}",
                            line_start=0,
                            line_end=0,
                            reasoning=finding['description'],
                        )],
                        suggestion=finding['fix'],
                    ))
            else:
                console.print("  [green]  Dependencies: clean[/]")
        except Exception as e:
            console.print(f"[dim]  Dependency scan skipped: {e}[/]")
        perf_timings['dep_scan'] = (time.monotonic() - t0) * 1000

        # Phase 2 + 2.5: Semgrep + Taint (PARALLEL — both CPU-bound)
        t0 = time.monotonic()
        console.print("\n[bold]  Phase 2: Semgrep + Taint analysis (parallel)[/]")
        semgrep_risks_all: list = []
        taint_risks_all: list = []

        def _run_semgrep(f: CodeFile):
            try:
                from core.semgrep_runner import analyze_with_semgrep
                return analyze_with_semgrep(f, config=request.rules[0], risk_counter_start=0)
            except Exception as e:
                console.print(f"[dim]  Semgrep skipped for {f.path}: {e}[/]")
                return []

        def _run_taint(f: CodeFile):
            try:
                if f.language.value == "c":
                    flows = self.taint.analyze_c(f.content, str(f.path))
                elif f.language.value == "python":
                    flows = self.taint.analyze_python(f.content, str(f.path))
                else:
                    flows = []
                return (f, flows)
            except Exception as e:
                console.print(f"[dim]  Taint skipped for {f.path}: {e}[/]")
                return (f, [])

        with ThreadPoolExecutor(max_workers=MAX_STATIC_WORKERS) as pool:
            semgrep_futures = {pool.submit(_run_semgrep, f): f for f in valid_files}
            taint_futures = {pool.submit(_run_taint, f): f for f in valid_files}

            for future in as_completed(semgrep_futures):
                f = semgrep_futures[future]
                try:
                    risks = future.result()
                    if risks:
                        console.print(f"  [red]  Semgrep {f.path}: {len(risks)} risks[/]")
                        semgrep_risks_all.extend(risks)
                except Exception:
                    pass

            for future in as_completed(taint_futures):
                f = taint_futures[future]
                try:
                    _, flows = future.result()
                    if flows:
                        console.print(f"  [red]  Taint {f.path}: {len(flows)} data flows[/]")
                        for flow in flows:
                            from core.models import Confidence, Evidence, Language, Risk, Severity
                            sev = Severity(flow.severity) if flow.severity in [s.value for s in Severity] else Severity.MEDIUM
                            taint_risks_all.append(Risk(
                                id=f"RISK-{len(all_risks) + len(semgrep_risks_all) + len(taint_risks_all) + 1:03d}",
                                title=f"Taint: {flow.description[:60]}",
                                description=flow.description,
                                severity=sev,
                                confidence=Confidence.HIGH if flow.confidence == "high" else Confidence.MEDIUM,
                                cwe_id=flow.cwe_id,
                                language=f.language,
                                file_path=f.path,
                                line_start=flow.sink_line,
                                line_end=flow.sink_line,
                                evidence=[Evidence(
                                    source="taint_analysis",
                                    snippet=f"{flow.source} -> {flow.sink}",
                                    line_start=flow.source_line,
                                    line_end=flow.sink_line,
                                    reasoning=f"Data flow: {flow.source} (line {flow.source_line}) -> {flow.sink} (line {flow.sink_line})",
                                )],
                                suggestion=flow.suggestion,
                            ))
                except Exception:
                    pass

        all_risks.extend(semgrep_risks_all)
        all_risks.extend(taint_risks_all)
        perf_timings['semgrep_taint'] = (time.monotonic() - t0) * 1000

        # Phase 3: LLM semantic analysis (PARALLEL — GPU-bound, limited concurrency)
        if request.enable_ai and self.semantic_analyzer:
            t0 = time.monotonic()
            console.print("\n[bold]  Phase 3: LLM semantic analysis (Agent 2, parallel)[/]")

            # Collect files that need LLM analysis
            llm_tasks: list[tuple[CodeFile, list[Risk]]] = []
            for f in valid_files:
                file_risks = [r for r in all_risks if r.file_path == f.path]
                if f.line_count < MIN_LINES_FOR_LLM and not file_risks:
                    console.print(f"  [dim]  {f.path}: skipped (small file)[/]")
                    continue
                llm_tasks.append((f, file_risks))

            # Run LLM analysis in parallel
            def _run_llm(task: tuple[CodeFile, list[Risk]]):
                f, file_risks = task
                try:
                    return f, self.semantic_analyzer.analyze(f, file_risks), None
                except Exception as e:
                    return f, None, e

            with ThreadPoolExecutor(max_workers=MAX_SEMANTIC_WORKERS) as pool:
                futures = [pool.submit(_run_llm, task) for task in llm_tasks]
                for future in as_completed(futures):
                    f, enriched, err = future.result()
                    if err:
                        console.print(f"  [yellow]  LLM failed for {f.path}: {err}[/]")
                    elif enriched:
                        all_risks = [r for r in all_risks if r.file_path != f.path]
                        all_risks.extend(enriched)
                        console.print(f"  [green]  {f.path}: {len(enriched)} risks[/]")

            perf_timings['agent2_llm'] = (time.monotonic() - t0) * 1000

        # State: VERIFY
        self.state = State.VERIFY
        t0 = time.monotonic()
        console.print("\n[bold]  Phase 4: Deep verification (Agent 3)[/]")
        mem_stats = self.memory.get_stats()
        console.print(
            f"  [dim]  Memory: {mem_stats['correct_patterns']} correct, "
            f"{mem_stats['error_patterns']} error patterns loaded[/]"
        )
        all_risks = self.verifier.verify_batch(valid_files, all_risks)
        perf_timings['agent3_verify'] = (time.monotonic() - t0) * 1000

        # State: REPORT
        self.state = State.REPORT
        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        model_desc = "static+semgrep"
        if request.enable_ai and self.llm:
            model_desc += "+llm"
        model_desc += "+verify+memory+cve"

        result = AnalysisResult(
            request_id=f"scan-{int(time.time())}",
            files_analyzed=len(valid_files),
            risks=all_risks,
            analysis_time_ms=elapsed_ms,
            model_used=model_desc,
        )

        console.print(f"\n[bold]  Phase 5: Report generation (Agent 4)[/]")
        t0 = time.monotonic()
        if output_format == "terminal" or output_format == "all":
            self.reporter.print_terminal(result)
        if output_format in ("json", "md", "all"):
            self.reporter.save_report(result, formats=["json", "md"])
        if output_format in ("sarif", "all"):
            self.reporter.save_report(result, formats=["sarif"])
        perf_timings['agent4_report'] = (time.monotonic() - t0) * 1000

        # Store timings in result
        result = result.model_copy(update={"perf_timings": perf_timings})

        # Print performance summary
        console.print("\n[bold cyan]  Performance Summary[/]")
        for phase, ms in perf_timings.items():
            pct = (ms / elapsed_ms * 100) if elapsed_ms > 0 else 0
            console.print(f"  [dim]{phase:>20}: {ms:>8.0f} ms ({pct:>5.1f}%)[/]")

        self.state = State.DONE
        console.print(f"\n[green]  Analysis complete. {result.total_risks} risks found in {elapsed_ms}ms.[/]")

        # Cleanup resources
        self.cve.close()

        return result

    def _validate_files(self, files: list[CodeFile]) -> list[CodeFile]:
        valid = []
        for f in files:
            if not f.content.strip():
                continue
            if f.language == Language.UNKNOWN:
                continue
            valid.append(f)
        return valid

    def _find_project_root(self, files: list[CodeFile]) -> Path:
        """Walk up directory tree to find project root."""
        markers = [
            "requirements.txt", "setup.py", "pyproject.toml",
            "Cargo.toml", "Makefile", "CMakeLists.txt",
            "package.json", "go.mod", "pom.xml",
        ]
        start = Path(files[0].path).resolve()
        current = start.parent if start.is_file() else start

        for _ in range(10):
            if any((current / m).exists() for m in markers):
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent

        return Path(files[0].path).parent

    def _transition(self, new_state: State) -> None:
        """Validate and execute state transition."""
        valid = VALID_TRANSITIONS.get(self.state, set())
        if new_state not in valid:
            raise ValueError(f"Invalid state transition: {self.state} -> {new_state}")
        self.state = new_state

    @property
    def current_state(self) -> str:
        return self.state.value
