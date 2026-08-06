"""BuildGuard command line interface."""

import json
import logging
import multiprocessing
import os
import sys
from pathlib import Path
from typing import cast

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console

from buildguard.benchmark import run_benchmark
from buildguard.config import Settings, load_settings
from buildguard.exceptions import BuildGuardError
from buildguard.rag.schemas import RagSearchInput
from buildguard.rag.service import create_rag_service
from buildguard.security.path_guard import PathGuard
from buildguard.storage.database import Database
from buildguard.system.environment_probe import EnvironmentProbe
from buildguard.utils.logging import configure_logging
from buildguard.workspace.manager import WorkspaceManager
from buildguard.workspace.retention import RetentionCleaner

app = typer.Typer(help="BuildGuard-Radeon local runtime tools", no_args_is_help=True)
runtime_mode_app = typer.Typer(
    help="Manage mutually exclusive online, indexing, and training modes.",
    no_args_is_help=True,
)
app.add_typer(runtime_mode_app, name="runtime-mode")
console = Console()
LOGGER = logging.getLogger(__name__)


def _settings(path: Path) -> Settings:
    settings = load_settings(path)
    configure_logging(settings.app.log_level)
    return settings


@app.command("validate-config")
def validate_config(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Validate and display redacted configuration."""
    try:
        settings = _settings(config)
        console.print_json(json.dumps(settings.safe_dump()))
        console.print("[green]Configuration valid[/green]")
    except (BuildGuardError, ValidationError) as exc:
        LOGGER.error("Configuration validation failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("probe-environment")
def probe_environment(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Inspect host, Radeon/ROCm tools, and the configured endpoint."""
    try:
        report = EnvironmentProbe(_settings(config)).probe()
        console.print_json(report.model_dump_json())
    except BuildGuardError as exc:
        LOGGER.error("Environment probe failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("benchmark-llm")
def benchmark_llm(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Benchmark deterministic mock or an approved local LLM."""
    try:
        result = run_benchmark(_settings(config))
        console.print_json(result.model_dump_json())
    except (BuildGuardError, httpx.HTTPError) as exc:
        LOGGER.error("LLM benchmark failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("competition-check")
def competition_check(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
    level: str = typer.Option(
        "full",
        help="Readiness level: agent, rag, vision, or full.",
    ),
) -> None:
    """Evaluate real-resource competition readiness for one delivery level."""
    from buildguard.evaluation.competition_readiness import (
        CompetitionLevel,
        CompetitionReadinessChecker,
    )

    allowed = {"agent", "rag", "vision", "full"}
    if level not in allowed:
        LOGGER.error("Unknown competition readiness level: %s", level)
        raise typer.Exit(code=2)
    try:
        report = CompetitionReadinessChecker(_settings(config)).run(
            cast(CompetitionLevel, level)
        )
        console.print_json(report.model_dump_json())
        if not report.ready_for(cast(CompetitionLevel, level)):
            raise typer.Exit(code=2)
    except (BuildGuardError, OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("Competition readiness check failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("ablation-report")
def ablation_report(
    input_dir: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(..., dir_okay=False),
) -> None:
    """Aggregate only provenance-complete measured ablation run records."""
    from buildguard.evaluation.ablation import aggregate_ablation_directory

    try:
        report = aggregate_ablation_directory(input_dir, output)
        console.print_json(report.model_dump_json())
        if report.status != "PASS":
            raise typer.Exit(code=2)
    except (OSError, ValueError) as exc:
        LOGGER.error("Ablation evidence aggregation failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("vision-dataset-check")
def vision_dataset_check(
    root: Path = typer.Option(..., exists=True, file_okay=False),
    report: Path = typer.Option(..., dir_okay=False),
    content_hash: bool = typer.Option(False, "--content-hash/--no-content-hash"),
) -> None:
    """Validate real COCO splits, boxes, classes, files, and data leakage."""
    from buildguard.evaluation.vision_dataset import audit_coco_dataset
    from buildguard.logging_system.jsonl_writer import atomic_write_json

    try:
        result = audit_coco_dataset(root, content_hash=content_hash)
        atomic_write_json(report, result)
        console.print_json(result.model_dump_json())
        if result.status != "PASS":
            raise typer.Exit(code=2)
    except (OSError, TypeError, ValueError) as exc:
        LOGGER.error("Vision dataset validation failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("vision-model-finalize")
def vision_model_finalize(
    source: Path = typer.Option(..., exists=True, file_okay=False),
    target: Path = typer.Option(..., file_okay=False),
    model_id: str = typer.Option(...),
    revision: str = typer.Option(...),
    source_uri: str = typer.Option(...),
    license_name: str = typer.Option(..., "--license"),
    validated_on_amd: bool = typer.Option(
        False, "--validated-on-amd/--not-validated-on-amd"
    ),
) -> None:
    """Preserve training output and create a non-overwriting deployment copy."""
    from buildguard.vision.model_artifact import finalize_vision_model

    try:
        manifest = finalize_vision_model(
            source,
            target,
            model_id=model_id,
            revision=revision,
            source_uri=source_uri,
            license_name=license_name,
            validated_on_amd=validated_on_amd,
        )
        console.print_json(json.dumps(manifest))
    except (OSError, TypeError, ValueError) as exc:
        LOGGER.error("Vision model finalization failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("evaluate-rag-ablation")
def evaluate_rag_ablation(
    cases: Path = typer.Option(..., exists=True, dir_okay=False),
    output_dir: Path = typer.Option(..., file_okay=False),
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Measure all retrieval variants against one real indexed corpus and case set."""
    import orjson

    from buildguard.api.app import create_backend
    from buildguard.logging_system.jsonl_writer import atomic_write_json
    from buildguard.rag.advanced.answer_grounding import AnswerGrounder
    from buildguard.rag.advanced.corrective_retriever import (
        create_advanced_rag_pipeline,
    )
    from buildguard.rag.advanced.evaluation import (
        AdvancedEvaluationExample,
        AdvancedRagEvaluator,
    )

    try:
        settings = _settings(config)
        target = output_dir.resolve()
        target.relative_to(settings.app.workspace_dir.resolve())
        payload = orjson.loads(cases.read_bytes())
        if not isinstance(payload, list) or not payload:
            raise ValueError("RAG ablation cases must be a non-empty JSON list")
        examples = [AdvancedEvaluationExample.model_validate(item) for item in payload]
        service = create_rag_service(settings)
        advanced = create_advanced_rag_pipeline(service, create_backend(settings))
        measured = AdvancedRagEvaluator(
            service,
            advanced,
            AnswerGrounder(settings.rag.advanced),
        ).evaluate(examples)
        names = {
            "BM25": ("retrieval", "bm25"),
            "Dense": ("retrieval", "dense"),
            "Hybrid": ("retrieval", "hybrid"),
            "Hybrid+Reranker": ("retrieval", "hybrid-reranker"),
            "Advanced Corrective RAG": ("advanced-rag", "corrective-grounded"),
        }
        for strategy, metrics in measured.items():
            group, variant = names[strategy]
            values = metrics.model_dump(mode="json")
            artifact = {
                "status": "PASS",
                "source": "measured",
                "mock": False,
                "group": group,
                "variant": variant,
                "sample_count": len(examples),
                "metrics": values,
            }
            atomic_write_json(target / f"{group}-{variant}-metrics.json", artifact)
            if strategy == "Hybrid+Reranker":
                artifact = {
                    **artifact,
                    "group": "advanced-rag",
                    "variant": "baseline",
                }
                atomic_write_json(
                    target / "advanced-rag-baseline-metrics.json", artifact
                )
        console.print_json(orjson.dumps({key: value.model_dump(mode="json") for key, value in measured.items()}).decode())
    except (BuildGuardError, OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("RAG ablation evaluation failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("evaluate-routing-ablation")
def evaluate_routing_ablation(
    cases: Path = typer.Option(..., exists=True, dir_okay=False),
    output_dir: Path = typer.Option(..., file_okay=False),
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Compare all four visual routers using real per-model prediction traces."""
    import orjson

    from buildguard.logging_system.jsonl_writer import atomic_write_json
    from buildguard.vision.routing.evaluation import (
        RoutingEvaluationCase,
        RoutingEvaluator,
    )
    from buildguard.vision.routing.router import VisualRouter

    try:
        settings = _settings(config)
        target = output_dir.resolve()
        target.relative_to(settings.app.workspace_dir.resolve())
        payload = orjson.loads(cases.read_bytes())
        if not isinstance(payload, list) or not payload:
            raise ValueError("Routing cases must be a non-empty JSON list")
        examples = [RoutingEvaluationCase.model_validate(item) for item in payload]
        models = [model for model in settings.vision.models if model.enabled]
        if len(models) < 2:
            raise ValueError("Routing ablation requires at least two enabled models")
        compared = RoutingEvaluator(
            VisualRouter(settings.vision.routing),
            models,
        ).compare(examples)
        for variant, result in compared.items():
            metrics = result.metrics
            if metrics.resource_source != "measured":
                raise ValueError(
                    f"{variant}: every selected model needs measured latency and VRAM"
                )
            artifact = {
                "status": "PASS",
                "source": "measured",
                "mock": False,
                "group": "routing",
                "variant": variant,
                "sample_count": len(examples),
                "metrics": {
                    "map": metrics.map,
                    "recall": metrics.recall,
                    "high_risk_recall": metrics.high_risk_recall,
                    "model_calls": float(metrics.call_count),
                    "latency_ms": metrics.latency_ms,
                    "peak_vram_mb": metrics.vram_mb,
                    "call_reduction": metrics.call_reduction,
                    "guard_rate": metrics.guard_rate,
                },
            }
            atomic_write_json(target / f"routing-{variant}-metrics.json", artifact)
        console.print_json(
            orjson.dumps(
                {
                    key: value.metrics.model_dump(mode="json")
                    for key, value in compared.items()
                }
            ).decode()
        )
    except (BuildGuardError, OSError, TypeError, ValueError, RuntimeError) as exc:
        LOGGER.error("Routing ablation evaluation failed: %s", exc)
        raise typer.Exit(code=2) from exc


def _workspace(settings: Settings) -> WorkspaceManager:
    return WorkspaceManager(settings.app.workspace_dir)


def _database(settings: Settings, manager: WorkspaceManager) -> Database:
    configured = settings.app.database_path.resolve()
    try:
        configured.relative_to(manager.root)
    except ValueError as exc:
        raise BuildGuardError("Database path must remain inside workspace") from exc
    return Database(configured)


def _runtime_mode_manager(settings: Settings) -> object:
    from buildguard.runtime_mode import RuntimeModeManager

    return RuntimeModeManager(settings.runtime, settings.app.workspace_dir)


@runtime_mode_app.command("status")
def runtime_mode_status(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Show the persisted runtime mode."""
    from buildguard.runtime_mode import RuntimeModeManager

    manager = cast(RuntimeModeManager, _runtime_mode_manager(_settings(config)))
    console.print_json(manager.status().model_dump_json())


@runtime_mode_app.command("enter")
def runtime_mode_enter(
    mode: str = typer.Argument(..., help="online, indexing, or training"),
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Enter one mode, rejecting active indexing/training conflicts."""
    from buildguard.runtime_mode import (
        RuntimeMode,
        RuntimeModeConflict,
        RuntimeModeManager,
    )

    try:
        selected = RuntimeMode(mode.casefold())
        manager = cast(RuntimeModeManager, _runtime_mode_manager(_settings(config)))
        console.print_json(manager.enter(selected).model_dump_json())
    except (ValueError, RuntimeModeConflict) as exc:
        LOGGER.error("Runtime mode transition rejected: %s", exc)
        raise typer.Exit(code=2) from exc


@runtime_mode_app.command("leave")
def runtime_mode_leave(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Leave indexing/training and return to online mode."""
    from buildguard.runtime_mode import RuntimeModeManager

    manager = cast(RuntimeModeManager, _runtime_mode_manager(_settings(config)))
    console.print_json(manager.leave().model_dump_json())


@app.command("init-workspace")
def init_workspace(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Create the runtime tree and a redacted run manifest."""
    try:
        settings = _settings(config)
        manager = _workspace(settings)
        manifest = manager.start_run(settings)
        console.print_json(manifest.model_dump_json())
    except (BuildGuardError, OSError, ValueError) as exc:
        LOGGER.error("Workspace initialization failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("db-init")
def db_init(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Initialize all SQLite tables."""
    try:
        settings = _settings(config)
        manager = _workspace(settings)
        manager.initialize()
        database = _database(settings, manager)
        database.initialize()
        console.print_json(json.dumps(database.check()))
        database.dispose()
    except (BuildGuardError, OSError, ValueError) as exc:
        LOGGER.error("Database initialization failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("db-check")
def db_check(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Check SQLite connectivity and list initialized tables."""
    try:
        settings = _settings(config)
        database = _database(settings, _workspace(settings))
        console.print_json(json.dumps(database.check()))
        database.dispose()
    except (BuildGuardError, OSError, ValueError) as exc:
        LOGGER.error("Database check failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("retention-cleanup")
def retention_cleanup(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
    dry_run: bool = typer.Option(True, "--dry-run/--execute"),
) -> None:
    """List expired artifacts; deletion requires --execute and enabled config."""
    try:
        settings = _settings(config)
        manager = _workspace(settings)
        manager.initialize()
        result = RetentionCleaner(manager, settings.app.retention).cleanup(dry_run=dry_run)
        console.print_json(result.model_dump_json())
    except (BuildGuardError, OSError, ValueError) as exc:
        LOGGER.error("Retention cleanup failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("rag-ingest")
def rag_ingest(
    source: Path = typer.Argument(..., exists=True),
    project: str | None = typer.Option(None),
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Parse and incrementally index local standards."""
    try:
        settings = _settings(config)
        guard = PathGuard([path.resolve() for path in settings.rag.allowed_source_roots])
        safe_source = guard.resolve_read(source.resolve())
        results = create_rag_service(settings).ingest_path(safe_source, project)
        console.print_json(json.dumps([item.model_dump(mode="json") for item in results]))
        if any(item.status == "failed" for item in results):
            raise typer.Exit(code=2)
    except (BuildGuardError, OSError, ValueError, PermissionError) as exc:
        LOGGER.error("RAG ingest failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("rag-search")
def rag_search(
    query: str = typer.Argument(...),
    top_k: int = typer.Option(5, min=1, max=50),
    document: list[str] | None = typer.Option(None, "--document"),
    project: str | None = typer.Option(None),
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Search local construction standards."""
    try:
        result = create_rag_service(_settings(config)).search(
            RagSearchInput(
                query=query,
                top_k=top_k,
                document_filters=document or [],
                project_filter=project,
            )
        )
        console.print_json(result.model_dump_json())
    except (BuildGuardError, OSError, ValueError) as exc:
        LOGGER.error("RAG search failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("rag-status")
def rag_status(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Display local RAG corpus and adapter status."""
    try:
        console.print_json(create_rag_service(_settings(config)).status().model_dump_json())
    except (BuildGuardError, OSError, ValueError) as exc:
        LOGGER.error("RAG status failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("rag-validate-index")
def rag_validate_index(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Validate persisted index identity against current models and corpus."""
    try:
        result = create_rag_service(_settings(config)).validate_index()
        console.print_json(json.dumps(result))
        if not result["valid"]:
            raise typer.Exit(code=2)
    except (BuildGuardError, OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("RAG index validation failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("rag-rebuild")
def rag_rebuild(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Rebuild local indexes and write a fresh versioned index manifest."""
    try:
        result = create_rag_service(_settings(config)).rebuild()
        console.print_json(json.dumps(result))
    except (BuildGuardError, OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("RAG rebuild failed: %s", exc)
        raise typer.Exit(code=2) from exc


def _serve_api_process(config_path: str) -> None:
    import uvicorn

    settings = _settings(Path(config_path))
    from buildguard.api.app import create_app

    uvicorn.run(
        create_app(settings),
        host=settings.services.api_host,
        port=settings.services.api_port,
        log_level=settings.app.log_level.lower(),
    )


@app.command("serve-api")
def serve_api(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Serve the local FastAPI application on the configured loopback address."""
    _serve_api_process(str(config.resolve()))


@app.command("serve-ui")
def serve_ui(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Serve the eight-page Streamlit UI against the configured local API."""
    settings = _settings(config)
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError as exc:
        raise BuildGuardError(
            "Streamlit is not installed; install the declared project dependencies."
        ) from exc
    os.environ["BUILDGUARD_CONFIG"] = str(config.resolve())
    ui_script = Path(__file__).parent / "ui" / "app.py"
    sys.argv = [
        "streamlit",
        "run",
        str(ui_script),
        "--server.address",
        settings.services.ui_host,
        "--server.port",
        str(settings.services.ui_port),
        "--server.headless",
        "true",
    ]
    streamlit_cli.main()


@app.command("run-demo")
def run_demo(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Start the local API and UI together; stopping the UI stops the API child."""
    api_process = multiprocessing.Process(
        target=_serve_api_process,
        args=(str(config.resolve()),),
        daemon=True,
        name="buildguard-api",
    )
    api_process.start()
    try:
        serve_ui(config)
    finally:
        api_process.terminate()
        api_process.join(timeout=5)


@app.command("smoke-test")
def smoke_test(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Run the deterministic offline MVP image-to-report workflow."""
    from buildguard.smoke import run_smoke

    try:
        result = run_smoke(_settings(config))
        console.print_json(json.dumps(result))
        if not result["ok"]:
            raise typer.Exit(code=2)
    except (BuildGuardError, OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("MVP smoke test failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("benchmark-suite")
def benchmark_suite(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
    section: str = typer.Option(
        "all",
        help="all, agent, rag, vision, realtime, security, or rocm",
    ),
) -> None:
    """Run the local evaluation suite and atomically export JSON/Markdown."""
    from buildguard.api.app import create_backend
    from buildguard.evaluation.experiment_runner import (
        ExperimentRunner,
        SuiteSection,
    )

    allowed = {"all", "agent", "rag", "vision", "realtime", "security", "rocm"}
    if section not in allowed:
        LOGGER.error("Unknown benchmark section: %s", section)
        raise typer.Exit(code=2)
    try:
        settings = _settings(config)
        report = ExperimentRunner(
            settings,
            create_backend(settings),
        ).run(cast(SuiteSection, section))
        console.print_json(report.model_dump_json())
        if report.status == "failed" or (
            settings.evaluation.fail_on_missing_resources
            and not report.competition_ready
        ):
            raise typer.Exit(code=2)
    except (BuildGuardError, OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("Benchmark suite failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("evaluate-agent-cases")
def evaluate_agent_cases(
    cases: Path = typer.Option(..., exists=True, dir_okay=False),
    output: Path = typer.Option(
        Path("workspace/reports/evaluation/agent-results.jsonl"),
        dir_okay=False,
    ),
    resume: bool = typer.Option(True, "--resume/--no-resume"),
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Execute raw Agent JSONL cases and append measured per-case outcomes."""
    from buildguard.agent.production_tools import create_production_agent_tools
    from buildguard.api.app import create_backend
    from buildguard.evaluation.agent_harness import AgentExecutionHarness
    from buildguard.vision.service import create_vision_service

    try:
        settings = _settings(config)
        summary = AgentExecutionHarness(
            settings,
            create_backend(settings),
            create_production_agent_tools(
                create_vision_service(settings),
                create_rag_service(settings),
            ),
        ).run(
            cases, output, resume=resume
        )
        console.print_json(summary.model_dump_json())
        if summary.failed_cases:
            raise typer.Exit(code=2)
    except (BuildGuardError, OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("Agent evaluation failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("evaluate-rag-cases")
def evaluate_rag_cases(
    cases: Path = typer.Option(..., exists=True, dir_okay=False),
    output: Path = typer.Option(
        Path("workspace/reports/evaluation/rag-results.jsonl"),
        dir_okay=False,
    ),
    resume: bool = typer.Option(True, "--resume/--no-resume"),
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Execute raw RAG JSONL cases and append grounded outcomes."""
    from buildguard.api.app import create_backend
    from buildguard.evaluation.rag_harness import RagEvaluationHarness

    try:
        settings = _settings(config)
        summary = RagEvaluationHarness(
            settings,
            create_rag_service(settings),
            create_backend(settings),
        ).run(cases, output, resume=resume)
        console.print_json(summary.model_dump_json())
        if summary.failed_cases:
            raise typer.Exit(code=2)
    except (BuildGuardError, OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("RAG evaluation failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("tool-stability")
def tool_stability(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
    iterations: int = typer.Option(50, min=1, max=100_000),
) -> None:
    """Execute repeated capability-checked, audited local tool calls."""
    from buildguard.api.app import create_backend
    from buildguard.evaluation.experiment_runner import ExperimentRunner

    try:
        settings = _settings(config)
        result = ExperimentRunner(
            settings,
            create_backend(settings),
        ).run_tool_stability(iterations)
        console.print_json(result.model_dump_json())
        if result.status != "validated":
            raise typer.Exit(code=2)
    except (BuildGuardError, OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("Tool stability test failed: %s", exc)
        raise typer.Exit(code=2) from exc


@app.command("full-stress-check")
def full_stress_check(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Run orchestration locally; real performance remains an AMD Linux gate."""
    import platform

    from buildguard.evaluation.full_stress import (
        FullStressRunner,
        create_server_adapters,
    )

    adapters = (
        create_server_adapters(_settings(config))
        if platform.system() == "Linux"
        else None
    )
    report = FullStressRunner(adapters).run()
    console.print_json(report.model_dump_json())
    if report.status == "FAIL":
        raise typer.Exit(code=2)


@app.command("export-competition-results")
def export_competition_results(
    config: Path = typer.Option(Path("configs/app.yaml"), exists=True, dir_okay=False),
) -> None:
    """Package only a real, competition-ready benchmark report."""
    from buildguard.evaluation.report import export_competition_archive

    try:
        settings = _settings(config)
        archive = export_competition_archive(
            settings.evaluation.output_dir,
            settings.app.workspace_dir,
        )
        console.print_json(json.dumps({"archive": str(archive), "exported": True}))
    except (BuildGuardError, OSError, ValueError) as exc:
        LOGGER.error("Competition export failed: %s", exc)
        raise typer.Exit(code=2) from exc


if __name__ == "__main__":
    app()
