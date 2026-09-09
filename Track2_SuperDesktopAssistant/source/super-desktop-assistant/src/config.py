"""
全局配置管理器 —— 多供应商、多模型、按功能独立分配。

配置来源：
  1. config.json → 供应商列表、模型目录、功能分配
  2. .env        → API Key（敏感信息不进 config.json）
"""
import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, ClassVar

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


# ==================== 数据模型 ====================

@dataclass
class ModelSpec:
    """模型规格。"""
    id: str
    capabilities: list[str]          # ["llm", "vision", "stt", "tts", "image_gen"]
    display: str = ""
    default_params: dict = field(default_factory=dict)


@dataclass
class ProviderSpec:
    """供应商规格。"""
    name: str
    api_key: str
    base_url: str
    description: str = ""
    env_api_key: str = ""  # 环境变量名（用于错误提示，如 "OPENAI_API_KEY"）
    enabled: bool = True   # v3 P0b: 是否启用（禁用后路由跳过，可在对话中经 Layer 1 调整）
    models: dict[str, ModelSpec] = field(default_factory=dict)

    def get_model(self, model_id: str) -> ModelSpec | None:
        return self.models.get(model_id)

    def list_models_by_capability(self, capability: str) -> list[ModelSpec]:
        return [m for m in self.models.values() if capability in m.capabilities]

    @property
    def is_local(self) -> bool:
        """是否为本地推理供应商（vLLM/Ollama 或指向本机地址）。"""
        name_l = self.name.lower()
        if name_l in ("vllm", "ollama", "lmstudio", "local", "localhost"):
            return True
        base = (self.base_url or "").lower()
        return "127.0.0.1" in base or "localhost" in base


@dataclass
class Assignment:
    """功能 → (供应商, 模型) 的映射。"""
    provider: str
    model: str


@dataclass
class AppSettings:
    """全局应用设置（从 config.json -> settings 解析）。"""

    # 路径
    output_dir: str = "outputs"
    workspace_dir: str = "outputs"

    # ComfyUI
    comfyui_script: str = r"E:\ai_pict\rp_gen.py"
    comfyui_output_dir: str = r"E:\ai_pict\ComfyUI\output"
    comfyui_work_dir: str = r"E:\ai_pict"
    comfyui_default_size: str = "832x1216"
    comfyui_default_cfg: float = 4.5
    comfyui_default_steps: int = 30
    comfyui_timeout: int = 300

    # 执行引擎
    timeout_per_node: float = 120.0
    max_retries: int = 1
    max_llm_agents: int = 5
    max_tool_rounds: int = 8

    # ── v2.0: 按类型差异化超时 ──
    timeout_image: float = 120.0
    timeout_text: float = 30.0
    timeout_audio: float = 20.0

    # ── v2.0: Layer 1 上下文截断 ──
    max_context_turns: int = 6           # 最多保留对话轮次
    truncation_summary_chars: int = 50   # 截断摘要最大字数

    # ── v3 P0b: API 偏好 ──
    api_preference: str = "cloud_default"  # "local_first"（本地优先）| "cloud_default"（默认）

    # LLM 参数
    planner_temperature: float = 0.1
    allocator_temperature: float = 0.3
    allocator_max_tokens: int = 1024
    llm_agent_temperature: float = 0.3
    llm_agent_max_tokens: int = 4096
    translator_temperature: float = 0.5
    translator_max_tokens: int = 512
    editor_temperature: float = 0.6
    editor_max_tokens: int = 512

    # 类级别默认值常量（避免每次 from_dict 都创建 throwaway 实例）
    _DEFAULTS: ClassVar[dict] = {
        "output_dir": "outputs",
        "workspace_dir": "outputs",
        "comfyui_script": r"E:\ai_pict\rp_gen.py",
        "comfyui_output_dir": r"E:\ai_pict\ComfyUI\output",
        "comfyui_work_dir": r"E:\ai_pict",
        "comfyui_default_size": "832x1216",
        "comfyui_default_cfg": 4.5,
        "comfyui_default_steps": 30,
        "comfyui_timeout": 300,
        "timeout_per_node": 120.0,
        "max_retries": 1,
        "max_llm_agents": 5,
        "max_tool_rounds": 8,
        "timeout_image": 120.0,
        "timeout_text": 30.0,
        "timeout_audio": 20.0,
        "max_context_turns": 6,
        "truncation_summary_chars": 50,
        "api_preference": "cloud_default",
        "planner_temperature": 0.1,
        "allocator_temperature": 0.3,
        "allocator_max_tokens": 1024,
        "llm_agent_temperature": 0.3,
        "llm_agent_max_tokens": 4096,
        "translator_temperature": 0.5,
        "translator_max_tokens": 512,
        "editor_temperature": 0.6,
        "editor_max_tokens": 512,
    }

    @classmethod
    def from_dict(cls, d: dict | None) -> "AppSettings":
        if not d:
            return cls()
        comfy = d.get("comfyui", {})
        exec_cfg = d.get("execution", {})
        llm_cfg = d.get("llm_defaults", {})
        df = cls._DEFAULTS
        return cls(
            output_dir=d.get("output_dir", df["output_dir"]),
            workspace_dir=d.get("workspace_dir", df["workspace_dir"]),
            comfyui_script=comfy.get("script", df["comfyui_script"]),
            comfyui_output_dir=comfy.get("output_dir", df["comfyui_output_dir"]),
            comfyui_work_dir=comfy.get("work_dir", df["comfyui_work_dir"]),
            comfyui_default_size=comfy.get("default_size", df["comfyui_default_size"]),
            comfyui_default_cfg=comfy.get("default_cfg", df["comfyui_default_cfg"]),
            comfyui_default_steps=comfy.get("default_steps", df["comfyui_default_steps"]),
            comfyui_timeout=comfy.get("subprocess_timeout", df["comfyui_timeout"]),
            timeout_per_node=exec_cfg.get("timeout_per_node", df["timeout_per_node"]),
            max_retries=exec_cfg.get("max_retries", df["max_retries"]),
            max_llm_agents=exec_cfg.get("max_llm_agents", df["max_llm_agents"]),
            max_tool_rounds=exec_cfg.get("max_tool_rounds", df["max_tool_rounds"]),
            # ── v2.0 新字段 ──
            timeout_image=exec_cfg.get("timeout_image", df["timeout_image"]),
            timeout_text=exec_cfg.get("timeout_text", df["timeout_text"]),
            timeout_audio=exec_cfg.get("timeout_audio", df["timeout_audio"]),
            max_context_turns=exec_cfg.get("max_context_turns", df["max_context_turns"]),
            truncation_summary_chars=exec_cfg.get("truncation_summary_chars", df["truncation_summary_chars"]),
            api_preference=d.get("api_preference", df["api_preference"]),
            planner_temperature=llm_cfg.get("planner_temperature", df["planner_temperature"]),
            allocator_temperature=llm_cfg.get("allocator_temperature", df["allocator_temperature"]),
            allocator_max_tokens=llm_cfg.get("allocator_max_tokens", df["allocator_max_tokens"]),
            llm_agent_temperature=llm_cfg.get("llm_agent_temperature", df["llm_agent_temperature"]),
            llm_agent_max_tokens=llm_cfg.get("llm_agent_max_tokens", df["llm_agent_max_tokens"]),
            translator_temperature=llm_cfg.get("translator_temperature", df["translator_temperature"]),
            translator_max_tokens=llm_cfg.get("translator_max_tokens", df["translator_max_tokens"]),
            editor_temperature=llm_cfg.get("editor_temperature", df["editor_temperature"]),
            editor_max_tokens=llm_cfg.get("editor_max_tokens", df["editor_max_tokens"]),
        )


# ==================== ConfigManager ====================

class ConfigManager:
    """多供应商配置管理器。"""

    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.json"

        self._config_path = config_path

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"配置文件不存在: {config_path}\n"
                f"请从项目根目录运行，或检查 config.json 是否已创建。"
            )
        except json.JSONDecodeError as e:
            raise ValueError(
                f"配置文件 JSON 格式错误: {config_path}\n{e}"
            )

        self._providers: dict[str, ProviderSpec] = {}
        self._assignments: dict[str, Assignment] = {}
        self._settings: AppSettings = AppSettings()
        # v3 P6b: Layer 1 配置修改追踪（保存时按路径写回 config.json）
        self._config_changes: list[tuple[list[str], object]] = []
        # Phase B：ai-coin 全量迁移后，供应商/分配由 ai-coin 管理（config.json 只留 settings）
        self._ai_coin_managed = False
        self._load(raw)

    def _load(self, raw: dict):
        """解析配置。供应商/分配来源：ai-coin state（迁移后）或 config.json（迁移前）。"""
        providers_raw = raw.get("providers", {})
        assignments_raw = raw.get("assignments", {})
        settings_raw = raw.get("settings", {})

        # Phase B：若 ai-coin 可用，供应商/分配从其 state 读取（config.json 已瘦身）
        try:
            from .api.ai_coin_bridge import provider_state_for_config
            p_raw, a_raw, _pref = provider_state_for_config()
            if p_raw or a_raw:
                providers_raw = p_raw
                assignments_raw = a_raw
                self._ai_coin_managed = True
        except Exception as e:
            logger.warning(f"[CONFIG] ai-coin 路由不可用，回退 config.json: {e}")

        # 解析供应商
        for name, pdata in providers_raw.items():
            env_key = pdata.get("env_api_key", "")
            api_key = os.getenv(env_key, "")

            models = {}
            for mid, mdata in pdata.get("models", {}).items():
                models[mid] = ModelSpec(
                    id=mid,
                    capabilities=mdata.get("capabilities", []),
                    display=mdata.get("display", mid),
                    default_params=mdata.get("default_params", {}),
                )

            self._providers[name] = ProviderSpec(
                name=name,
                api_key=api_key,
                base_url=pdata.get("base_url", ""),
                description=pdata.get("description", ""),
                env_api_key=env_key,
                enabled=pdata.get("enabled", True),
                models=models,
            )

        # 解析功能分配（含验证）
        for cap, adata in assignments_raw.items():
            provider_name = adata.get("provider", "")
            model_id = adata.get("model", "")
            if not provider_name or not model_id:
                logger.warning(f"[CONFIG] 功能 '{cap}' 的分配信息不完整，跳过")
                continue
            # 验证 provider 存在
            if provider_name not in self._providers:
                logger.error(
                    f"[CONFIG] 功能 '{cap}' 引用了不存在的供应商 '{provider_name}'，"
                    f"可用: {list(self._providers.keys())}"
                )
                continue
            # 验证 model 存在于该 provider
            provider = self._providers[provider_name]
            if model_id not in provider.models:
                logger.error(
                    f"[CONFIG] 功能 '{cap}' 引用了供应商 '{provider_name}' "
                    f"中不存在的模型 '{model_id}'，"
                    f"可用: {list(provider.models.keys())}"
                )
                continue
            self._assignments[cap] = Assignment(
                provider=provider_name,
                model=model_id,
            )

        # 解析全局设置（可选，缺失时使用默认值）
        # Phase B：api_preference 若被 ai-coin 迁移进 state 而 config.json 未更新，则补上
        if "api_preference" not in settings_raw and self._ai_coin_managed:
            try:
                from .api.ai_coin_bridge import load_state
                _st = load_state()
                if _st and _st.get("api_preference"):
                    settings_raw = {**settings_raw, "api_preference": _st["api_preference"]}
            except Exception:
                pass
        self._settings = AppSettings.from_dict(settings_raw)

    # --- 查询接口 ---

    @property
    def settings(self) -> AppSettings:
        """获取全局应用设置。"""
        return self._settings

    def get_provider(self, name: str) -> ProviderSpec | None:
        return self._providers.get(name)

    def get_assignment(self, capability: str) -> Assignment | None:
        """获取某个功能当前分配的 (provider, model)。"""
        return self._assignments.get(capability)

    # ── 子能力回退 ──

    @staticmethod
    def _capability_chain(capability: str) -> list[str]:
        """子能力回退链：llm_reasoning → llm；普通能力仅自身。"""
        if capability.startswith("llm_") and capability != "llm":
            return [capability, "llm"]
        return [capability]

    @staticmethod
    def _base_capability(capability: str) -> str:
        """子能力的基础能力：llm_reasoning → llm。"""
        if capability.startswith("llm_"):
            return "llm"
        return capability

    # ── 路由解析 ──

    def resolve(self, capability: str) -> tuple[ProviderSpec, ModelSpec] | None:
        """
        解析功能 → (供应商实例, 模型实例)。

        支持 v3 P0b 特性：
        - 子能力路由：llm_reasoning / llm_creative / llm_summary，缺失时回退 llm
        - 禁用过滤：assignment 指向的 provider 被禁用时，自动降级到其他候选
        - 本地优先：api_preference=local_first 时优先本地推理供应商

        例: resolve("llm") → (mimo_provider, mimo-v2.5_spec)
        """
        # 1. 子能力回退链：优先 assignment 指定且 enabled 的 provider
        for cap in self._capability_chain(capability):
            assign = self.get_assignment(cap)
            if not assign:
                continue
            provider = self.get_provider(assign.provider)
            if not provider or not provider.enabled:
                continue
            model = provider.get_model(assign.model)
            if model:
                return provider, model

        # 2. 兜底：其他 enabled 候选（含本地优先排序）
        candidates = self.resolve_candidates(capability)
        return candidates[0] if candidates else None

    def resolve_candidates(
        self, capability: str
    ) -> list[tuple[ProviderSpec, ModelSpec]]:
        """
        返回候选 (provider, model) 列表，按 api_preference 排序，过滤 disabled。

        候选来源：
        1. assignment 子能力回退链指定的 (provider, model)
        2. 其他 enabled 且模型能力匹配的供应商

        排序：api_preference="local_first" 时本地供应商优先；默认保持配置顺序。
        供 api 层多后端降级使用。
        """
        base_cap = self._base_capability(capability)
        seen = set()
        candidates: list[tuple[ProviderSpec, ModelSpec]] = []

        # 1. assignment 子能力回退链
        for cap in self._capability_chain(capability):
            assign = self.get_assignment(cap)
            if not assign:
                continue
            provider = self.get_provider(assign.provider)
            if not provider or not provider.enabled:
                continue
            model = provider.get_model(assign.model)
            if not model:
                continue
            key = (provider.name, model.id)
            if key not in seen:
                seen.add(key)
                candidates.append((provider, model))

        # 2. 其他 enabled 供应商的同能力模型
        for pname, p in self._providers.items():
            if not p.enabled:
                continue
            for m in p.list_models_by_capability(base_cap):
                key = (pname, m.id)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append((p, m))

        # 3. 本地优先排序
        if self._settings.api_preference == "local_first":
            candidates.sort(key=lambda x: (0 if x[0].is_local else 1,))

        return candidates

    # --- 列表接口（给 UI 用） ---

    def list_providers(self) -> list[ProviderSpec]:
        return list(self._providers.values())

    def list_capabilities(self) -> list[str]:
        """列出所有功能类型。"""
        caps = set()
        for p in self._providers.values():
            for m in p.models.values():
                caps.update(m.capabilities)
        return sorted(caps)

    def list_models_for_capability(self, capability: str) -> list[dict]:
        """
        列出支持某功能的所有模型（供 UI 下拉选择）。
        返回: [{"provider": "openai", "model": "gpt-4o", "display": "GPT-4o"}, ...]
        """
        result = []
        for pname, p in self._providers.items():
            for m in p.list_models_by_capability(capability):
                result.append({
                    "provider": pname,
                    "model": m.id,
                    "display": f"[{pname}] {m.display or m.id}",
                })
        return result

    def get_current_assignment_display(self, capability: str) -> str:
        """当前分配的可读描述。"""
        assign = self.get_assignment(capability)
        if not assign:
            return "未分配"

        provider = self.get_provider(assign.provider)
        if not provider:
            return f"{assign.provider}/{assign.model}"

        model = provider.get_model(assign.model)
        display = model.display if model else assign.model
        return f"[{assign.provider}] {display}"

    # --- 写入接口 ---

    def set_assignment(self, capability: str, provider_name: str, model_id: str):
        """动态修改功能分配。

        Phase B：ai-coin 管理模式下写入 state.json；否则仅内存（由 save_to_file 落 config.json）。
        """
        self._assignments[capability] = Assignment(
            provider=provider_name,
            model=model_id,
        )
        if self._ai_coin_managed:
            try:
                from .api.ai_coin_bridge import set_assignment as _bridge_set
                _bridge_set(capability, provider_name, model_id)
            except Exception as e:
                logger.warning(f"[CONFIG] ai-coin 写入分配失败: {e}")

    # ── v3 P6b: Layer 1 配置修改（唯一拥有配置修改权限的层） ──

    def update_setting(self, key: str, value) -> str:
        """更新设置项（白名单）。返回确认描述。

        支持：workspace_dir / output_dir / api_preference / temperature / max_tokens
        """
        s = self._settings
        if key == "workspace_dir":
            s.workspace_dir = str(value)
            self._config_changes.append((["settings", "workspace_dir"], str(value)))
            return f"工作目录已改为 {value}"
        if key == "output_dir":
            s.output_dir = str(value)
            self._config_changes.append((["settings", "output_dir"], str(value)))
            return f"输出目录已改为 {value}"
        if key == "api_preference":
            if value not in ("local_first", "cloud_default"):
                raise ValueError("api_preference 只能为 local_first（本地优先）或 cloud_default（默认）")
            s.api_preference = value
            if self._ai_coin_managed:
                # Phase B：ai-coin 模式下同步写 config.json settings + ai-coin state
                from .api.ai_coin_bridge import set_api_preference
                set_api_preference(value)
            else:
                self._config_changes.append((["settings", "api_preference"], value))
            return f"API 偏好已设为 {'本地优先' if value == 'local_first' else '云端默认'}"
        if key == "temperature":
            v = float(value)
            for attr, path in [
                ("planner_temperature", ["settings", "llm_defaults", "planner_temperature"]),
                ("allocator_temperature", ["settings", "llm_defaults", "allocator_temperature"]),
                ("llm_agent_temperature", ["settings", "llm_defaults", "llm_agent_temperature"]),
                ("translator_temperature", ["settings", "llm_defaults", "translator_temperature"]),
                ("editor_temperature", ["settings", "llm_defaults", "editor_temperature"]),
            ]:
                setattr(s, attr, v)
                self._config_changes.append((path, v))
            return f"LLM temperature 已统一设为 {value}"
        if key == "max_tokens":
            v = int(value)
            for attr, path in [
                ("allocator_max_tokens", ["settings", "llm_defaults", "allocator_max_tokens"]),
                ("llm_agent_max_tokens", ["settings", "llm_defaults", "llm_agent_max_tokens"]),
                ("translator_max_tokens", ["settings", "llm_defaults", "translator_max_tokens"]),
                ("editor_max_tokens", ["settings", "llm_defaults", "editor_max_tokens"]),
            ]:
                setattr(s, attr, v)
                self._config_changes.append((path, v))
            return f"LLM max_tokens 已统一设为 {value}"
        raise ValueError(f"不支持的设置项: {key}（白名单: workspace_dir/output_dir/api_preference/temperature/max_tokens）")

    def set_provider_enabled(self, provider_name: str, enabled: bool) -> str:
        """启用/禁用供应商。"""
        p = self.get_provider(provider_name)
        if not p:
            raise ValueError(f"供应商不存在: {provider_name}")
        p.enabled = bool(enabled)
        if self._ai_coin_managed:
            # Phase B：ai-coin 模式下启停写 state.json
            from .api.ai_coin_bridge import set_provider_enabled as _bridge_enable
            _bridge_enable(provider_name, enabled)
        else:
            self._config_changes.append(
                (["providers", provider_name, "enabled"], p.enabled)
            )
        return f"{provider_name} 已{'启用' if p.enabled else '禁用'}"

    def save_to_file(self, config_path: str | None = None) -> bool:
        """原子写入：读-改-写 + 临时文件 rename，带重试机制防竞态。

        M6 修复：同一进程多线程并发保存用模块级写锁串行化；
        临时文件名加 uuid，避免同进程线程间 pid 命名碰撞互相覆盖。

        Returns:
            bool: 是否保存成功。成功时清空已应用的 _config_changes。
        """
        import tempfile
        import time

        target = Path(config_path or self._config_path)
        max_retries = 3
        with _config_save_lock:
            return self._save_to_file_locked(target, max_retries)

    def _save_to_file_locked(self, target: Path, max_retries: int) -> bool:
        import time
        import uuid

        for attempt in range(max_retries):
            try:
                with open(target, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError) as e:
                logger.error(f"[CONFIG] 无法读取配置文件，取消保存: {e}")
                return False

            # 合并当前内存中的 assignments 到读取的 raw 中
            # Phase B：ai-coin 管理模式下分配在 state.json，不回写 config.json
            if not self._ai_coin_managed:
                raw["assignments"] = {
                    cap: {"provider": a.provider, "model": a.model}
                    for cap, a in self._assignments.items()
                }

            # v3 P6b: 应用 Layer 1 修改的 settings / provider 配置（按路径写回）
            for path, value in self._config_changes:
                node = raw
                ok = True
                for part in path[:-1]:
                    if isinstance(node, dict):
                        node = node.setdefault(part, {})
                    else:
                        ok = False
                        break
                if ok and isinstance(node, dict):
                    node[path[-1]] = value

            # M6 修复：pid + uuid 临时名，避免同进程线程间冲突
            tmp = target.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}.json")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)

                # 跨平台原子 rename — 在 Windows 上 replace 是原子的
                # （如果目标存在会先删除，NTFS 保证原子性）
                tmp.replace(target)
                logger.info(f"[CONFIG] 已保存 {len(self._assignments)} 个功能分配")
                # 已落盘，清空变更记录避免累积重复写回
                self._config_changes.clear()
                return True
            except Exception as e:
                logger.error(f"[CONFIG] 保存配置失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                # 清理临时文件
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))
        logger.error(f"[CONFIG] 保存配置最终失败（已重试 {max_retries} 次）")
        return False


# ==================== 单例 ====================

import threading

_config: ConfigManager | None = None
_config_lock = threading.Lock()
# M6 修复：配置保存写锁（Gradio 多线程并发 save_to_file 时串行化）
_config_save_lock = threading.Lock()


def get_config() -> ConfigManager:
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = ConfigManager()
    return _config


def reload_config():
    global _config
    with _config_lock:
        _config = ConfigManager()
    # 清空旧的 API 客户端缓存，确保使用新配置的 key/URL
    from .api._client import clear_client_cache
    clear_client_cache()
    # 刷新工具白名单目录
    from .agents.tools import _refresh_allowed_paths
    _refresh_allowed_paths()
    return _config
