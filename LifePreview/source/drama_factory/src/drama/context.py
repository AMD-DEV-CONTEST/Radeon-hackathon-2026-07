"""流水线上下文：集中持有项目路径、配置、模型路由、ComfyUI 客户端。

所有 agent 通过 ctx 访问共享资源，避免到处传一堆参数。
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from collections.abc import Callable

from .comfy_client import ComfyClient
from .llm_client import LLMRouter
from .utils.files import ensure_dir, load_yaml
from .runtime import CancellationToken


# ---------------------------------------------------------------------------
# 镜头级日志路由：线程本地 + 自定义 Handler
# ---------------------------------------------------------------------------
# 各 agent(关键帧/视频/配音/对口型)在线程池里并行处理不同镜头，全部走同一个
# project logger。为了把"某个镜头运行期间产生的所有日志"额外汇聚到
# logs/shots/<shot_id>.log，用线程本地变量记下当前线程正在处理哪个 shot，
# 自定义 Handler 在 emit 时据此把记录追加到对应文件。无 shot_id 时什么都不做
# (普通的 stream/file handler 仍照常输出)。
_SHOT_CTX = threading.local()


def _environment_yaml(environment_name: str) -> dict[str, Any] | None:
    configured = os.getenv(environment_name, "").strip()
    if not configured:
        return None
    path = Path(configured)
    if not path.is_file():
        raise RuntimeError(f"{environment_name} must point to a YAML file")
    try:
        payload = load_yaml(path)
    except Exception:
        raise RuntimeError(
            f"{environment_name} must contain valid YAML"
        ) from None
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) for key in payload
    ):
        raise RuntimeError(
            f"{environment_name} must contain a YAML mapping"
        )
    return payload


def _recursive_merge(
    baseline: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(baseline)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _recursive_merge(current, value)
        else:
            merged[key] = value
    return merged


class _ShotLogHandler(logging.Handler):
    """把当前线程绑定的镜头日志额外落盘到 logs/shots/<shot_id>.log。

    - emit 时读取线程本地 shot_id；为空则直接跳过(交给其它 handler)。
    - 以追加方式打开 utf-8 文件，目录懒创建。
    - 任何异常都吞掉(包成 try/except)，确保日志系统永不拖垮流水线;
      dry-run 下同样安全(只是多写一个文本文件)。
    """

    def __init__(self, shots_dir: Path) -> None:
        super().__init__()
        self._shots_dir = Path(shots_dir)

    def emit(self, record: logging.LogRecord) -> None:
        shot_id = getattr(_SHOT_CTX, "shot_id", None)
        if not shot_id:
            return
        try:
            msg = self.format(record)
            self._shots_dir.mkdir(parents=True, exist_ok=True)
            target = self._shots_dir / f"{shot_id}.log"
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
        except Exception:  # noqa: BLE001 — 日志写入失败绝不影响主流程
            self.handleError(record)


@dataclass
class ProjectPaths:
    """单部小说项目的标准目录布局。"""
    root: Path
    @property
    def bible(self): return ensure_dir(self.root / "bible")
    @property
    def chapters(self): return ensure_dir(self.root / "chapters")
    @property
    def shots(self): return ensure_dir(self.root / "shots")
    @property
    def assets_chars(self): return ensure_dir(self.root / "assets" / "characters")
    @property
    def assets_scenes(self): return ensure_dir(self.root / "assets" / "scenes")
    @property
    def keyframes(self): return ensure_dir(self.root / "keyframes")
    @property
    def clips(self): return ensure_dir(self.root / "clips")
    @property
    def audio(self): return ensure_dir(self.root / "audio")
    @property
    def subtitles(self): return ensure_dir(self.root / "subtitles")
    @property
    def output(self): return ensure_dir(self.root / "output")
    @property
    def logs(self): return ensure_dir(self.root / "logs")


class _BrokeredComfyClient:
    """Resolve a ComfyUI instance only after an exclusive GPU lease is held."""

    def __init__(
        self,
        context: "Context",
        *,
        model_name: str,
        min_vram_mib: int,
    ) -> None:
        self._context = context
        self._model_name = model_name
        self._min_vram_mib = min_vram_mib
        self._uploads: list[tuple[Path, str, str]] = []
        self.base = "gpu-broker://pending"

    @staticmethod
    def load_workflow(path: str | Path) -> dict:
        return ComfyClient.load_workflow(path)

    @staticmethod
    def inject(workflow: dict, params: dict[str, Any]) -> dict:
        return ComfyClient.inject(workflow, params)

    def upload_file(
        self,
        path: str | Path,
        *,
        field: str = "image",
        subfolder: str = "",
    ) -> str:
        candidate = Path(path)
        self._uploads.append((candidate, field, subfolder))
        return candidate.name

    def upload_image(self, path: str | Path, subfolder: str = "") -> str:
        return self.upload_file(path, field="image", subfolder=subfolder)

    def upload_audio(self, path: str | Path, subfolder: str = "") -> str:
        return self.upload_file(path, field="image", subfolder=subfolder)

    def run(self, workflow: dict, out_dir: str | Path, **kwargs: Any) -> list[Path]:
        manager = self._context.gpu_lease_manager
        with manager.lease_for(
            service_name="douyin-drama-comfy",
            model_name=self._model_name,
            min_vram_mib=self._min_vram_mib,
            metadata={"client": "douyin_analysis_drama_worker"},
        ) as active:
            client = self._context.comfy_workers[
                active.gpu_index % len(self._context.comfy_workers)
            ]
            self.base = client.base
            try:
                active.check(self._context.check_cancelled)
                for path, field, subfolder in self._uploads:
                    client.upload_file(path, field=field, subfolder=subfolder)
                    active.check(self._context.check_cancelled)
                return client.run(
                    workflow,
                    out_dir,
                    check_cb=lambda: active.check(self._context.check_cancelled),
                    **kwargs,
                )
            finally:
                self._uploads.clear()


class Context:
    def __init__(self, project_root: str | Path, config_dir: str | Path,
                 dry_run: bool = False,
                 cancellation: CancellationToken | None = None,
                 state_listener: Callable[[dict[str, Any]], None] | None = None,
                 gpu_lease_manager: Any | None = None,
                 video_providers: dict[str, Any] | None = None,
                 credential_resolver: Callable[[str, str], str] | None = None):
        self.dry_run = dry_run
        self.cancellation = cancellation or CancellationToken()
        self.state_listener = state_listener
        self.gpu_lease_manager = gpu_lease_manager
        if video_providers is None:
            # R3 video execution is local-only.  Cloud video providers may
            # still exist as explicit legacy adapters, but are never a
            # runtime default or an implicit fallback.
            video_providers = {}
        self.video_providers = dict(video_providers)
        self.paths = ProjectPaths(Path(project_root))
        ensure_dir(self.paths.root)

        # 实时进度跟踪：各 agent 写镜头级步进度 → <project>/progress.json,
        # 供 tools/progress_monitor.py(命令行)与 Web 控制台读取。
        from .progress import ProgressTracker
        self.progress = ProgressTracker(self.paths.root)

        self.config_dir = Path(config_dir)
        self.models_cfg = self.config_dir / "models.yaml"
        self.pipeline = load_yaml(self.config_dir / "pipeline.yaml")
        pipeline_override = _environment_yaml(
            "FACTORY_PIPELINE_OVERRIDE_FILE"
        )
        if pipeline_override is not None:
            self.pipeline = _recursive_merge(
                self.pipeline,
                pipeline_override,
            )
        comfy_override = _environment_yaml("FACTORY_COMFY_CONFIG_FILE")
        self.comfy_cfg = (
            comfy_override
            if comfy_override is not None
            else load_yaml(self.config_dir / "comfyui.yaml")
        )
        if comfy_override is not None:
            instances = self.comfy_cfg.get("instances")
            timeout_sec = self.comfy_cfg.get("timeout_sec", 1800)
            if (
                not isinstance(instances, list)
                or not instances
                or any(
                    not isinstance(instance, dict)
                    or not isinstance(instance.get("base_url"), str)
                    or not instance["base_url"].strip()
                    for instance in instances
                )
                or isinstance(timeout_sec, bool)
                or not isinstance(timeout_sec, (int, float))
                or timeout_sec <= 0
            ):
                raise RuntimeError(
                    "FACTORY_COMFY_CONFIG_FILE contains invalid settings"
                )

        # 分层模型路由
        self.llm = LLMRouter(
            self.models_cfg,
            dry_run=dry_run,
            credential_resolver=credential_resolver,
        )

        # ComfyUI 客户端数量完全由选中的 comfyui YAML 声明。
        self.comfy_workers: list[ComfyClient] = []
        for index, inst in enumerate(
            self.comfy_cfg.get("instances")
            or [{"base_url": "http://127.0.0.1:8188"}]
        ):
            base_url = os.getenv(
                f"DRAMA_COMFY_BASE_{index}",
                inst["base_url"],
            )
            self.comfy_workers.append(
                ComfyClient(base_url, dry_run=dry_run,
                            timeout_sec=self.comfy_cfg.get("timeout_sec", 1800)))

        self.workflow_dir = Path(
            os.getenv(
                "FACTORY_WORKFLOW_DIR",
                str(self.config_dir.parent / "workflows"),
            )
        )
        self.prompt_dir = Path(
            os.getenv(
                "FACTORY_PROMPT_DIR",
                str(self.config_dir.parent / "prompts"),
            )
        )

        self.log = self._setup_logger()

    def comfy(
        self,
        shard: int = 0,
        *,
        model_name: str = "drama-comfy-workflow",
        min_vram_mib: int = 16384,
    ) -> ComfyClient | _BrokeredComfyClient:
        """Return a direct client for development or a broker-leased proxy."""
        self.cancellation.check()
        if self.gpu_lease_manager is not None and not self.dry_run:
            return _BrokeredComfyClient(
                self,
                model_name=model_name,
                min_vram_mib=min_vram_mib,
            )
        return self.comfy_workers[shard % len(self.comfy_workers)]

    def check_cancelled(self) -> None:
        self.cancellation.check()

    @property
    def n_gpus(self) -> int:
        return len(self.comfy_workers)

    def workflow_path(self, name: str) -> Path:
        return self.workflow_dir / name

    def prompt_template(self, name: str) -> str:
        p = self.prompt_dir / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def cfg(self, *keys: str, default: Any = None) -> Any:
        """从 pipeline.yaml 取嵌套配置: ctx.cfg('video', 'resolution')。"""
        node: Any = self.pipeline
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def _setup_logger(self) -> logging.Logger:
        log = logging.getLogger(f"drama.{self.paths.root.name}")
        log.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        if not log.handlers:
            sh = logging.StreamHandler(); sh.setFormatter(fmt); log.addHandler(sh)
            fh = logging.FileHandler(self.paths.logs / "pipeline.log", encoding="utf-8")
            fh.setFormatter(fmt); log.addHandler(fh)
        # 镜头级 Handler 单独保证存在(即便 logger 已被复用过也只挂一次)，
        # 这样多次构造同名项目的 Context 也不会重复输出。
        if not any(isinstance(h, _ShotLogHandler) for h in log.handlers):
            shot_h = _ShotLogHandler(self.paths.logs / "shots")
            shot_h.setFormatter(fmt)
            log.addHandler(shot_h)
        return log

    @contextlib.contextmanager
    def shot_log(self, shot_id: str) -> Iterator[None]:
        """在 with 块内，把当前线程产生的所有日志额外汇聚到
        logs/shots/<shot_id>.log。

        线程本地：并行 worker 各自绑定自己的 shot_id，互不串扰。
        全程 try/except 包裹，保证即使设置/还原失败也不会中断流水线;
        退出时恢复进入前的 shot_id(支持潜在的嵌套/复用)。
        """
        prev = getattr(_SHOT_CTX, "shot_id", None)
        try:
            _SHOT_CTX.shot_id = shot_id
        except Exception:  # noqa: BLE001 — 设置线程本地失败也不该中断主流程
            pass
        try:
            yield
        finally:
            try:
                _SHOT_CTX.shot_id = prev
            except Exception:  # noqa: BLE001
                pass
