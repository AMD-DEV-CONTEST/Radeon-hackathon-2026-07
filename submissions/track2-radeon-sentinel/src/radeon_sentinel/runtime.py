"""Runtime assembly shared by the CLI and demo UI."""

from pathlib import Path

from .agent import RadeonSentinel
from .config import Settings
from .memory import CaseMemory
from .model import MockModelClient, OpenAICompatibleModelClient
from .retrieval import LocalRetriever
from .tools import DiagnosticEnvironment


def build_agent(settings: Settings, incident_name: str) -> RadeonSentinel:
    incident_path = _resolve_incident(settings.incident_dir, incident_name)
    environment = DiagnosticEnvironment.from_json(incident_path)
    retriever = LocalRetriever.from_directory(settings.runbook_dir)
    memory = CaseMemory(settings.database_path)

    if settings.model_mode == "openai":
        model = OpenAICompatibleModelClient(
            base_url=settings.model_base_url,
            model=settings.model_name,
            api_key=settings.model_api_key,
            timeout_seconds=settings.request_timeout_seconds,
        )
    else:
        model = MockModelClient()
    return RadeonSentinel(
        model=model,
        retriever=retriever,
        memory=memory,
        environment=environment,
    )


def _resolve_incident(incident_dir: Path, incident_name: str) -> Path:
    path = Path(incident_name)
    if path.suffix == ".json" and path.is_file():
        return path
    candidate = Path(incident_dir) / f"{incident_name}.json"
    if not candidate.is_file():
        available = ", ".join(
            sorted(item.stem for item in Path(incident_dir).glob("*.json"))
        )
        raise FileNotFoundError(
            f"Unknown incident '{incident_name}'. Available: {available}"
        )
    return candidate
