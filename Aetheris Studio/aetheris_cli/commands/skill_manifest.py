"""
Declarative skill manifests and auto-config planning model ported from ROCm CLI.
Provides Step definitions, DetectSpec endpoint mappings, and auto-config plan generation for local LLM engines.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


LEMONADE_PORT = 13305
LEMONADE_ENDPOINT = "http://localhost:13305/v1"
VLLM_PORT = 8000
VLLM_ENDPOINT = "http://localhost:8000/v1"
ROCM_SERVE_PORT = 11435
ROCM_SERVE_ENDPOINT = "http://localhost:11435/v1"


class StepKind(Enum):
    CHECK = "check"
    RUN = "run"
    DOWNLOAD = "download"
    WRITE_CONFIG = "write_config"


@dataclass
class Step:
    kind: StepKind
    command: str = ""
    cmd: str = ""
    args: List[str] = field(default_factory=list)
    url: str = ""
    dest: str = ""
    key: str = ""
    value: str = ""

    def describe(self) -> str:
        if self.kind == StepKind.CHECK:
            return f"check: {self.command}"
        elif self.kind == StepKind.RUN:
            args_str = " ".join(self.args)
            return f"run: {self.cmd} {args_str}".strip()
        elif self.kind == StepKind.DOWNLOAD:
            return f"download: {self.url} -> {self.dest}"
        elif self.kind == StepKind.WRITE_CONFIG:
            return f"write-config: {self.key} = {self.value}"
        return ""


class DetectKind(Enum):
    BINARY = "binary"
    ENDPOINT = "endpoint"


@dataclass
class DetectSpec:
    kind: DetectKind
    target: str


@dataclass
class SkillManifest:
    name: str
    description: str
    requires: List[str] = field(default_factory=list)
    detect: Optional[DetectSpec] = None
    steps: List[Step] = field(default_factory=list)


@dataclass
class ConfigChange:
    chat_url: str
    default_engine: str


@dataclass
class AutoConfigPlan:
    set_chat_url: Optional[str] = None
    set_default_engine: Optional[str] = None
    kept_existing_chat: bool = False

    @property
    def is_noop(self) -> bool:
        return self.set_chat_url is None and self.set_default_engine is None


def auto_config_change(detected_endpoint: Optional[str]) -> Optional[ConfigChange]:
    if not detected_endpoint:
        return None

    if str(LEMONADE_PORT) in detected_endpoint:
        engine = "lemonade"
    elif str(VLLM_PORT) in detected_endpoint:
        engine = "vllm"
    else:
        engine = "local"

    return ConfigChange(chat_url=detected_endpoint, default_engine=engine)


def auto_config_plan(detected_endpoint: Optional[str], chat_url_configured: bool = False) -> AutoConfigPlan:
    change = auto_config_change(detected_endpoint)
    if not change:
        return AutoConfigPlan()

    return AutoConfigPlan(
        set_chat_url=None if chat_url_configured else change.chat_url,
        set_default_engine=change.default_engine,
        kept_existing_chat=chat_url_configured,
    )
