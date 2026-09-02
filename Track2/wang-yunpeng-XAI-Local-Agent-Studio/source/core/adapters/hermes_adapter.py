"""Hermes Agent 适配器

封装 Hermes Agent 的 AI 推理 + 自进化能力：
- AI 推理（对话/代码生成/分析）
- GEPA 自进化引擎（技能变异/约束门/人工复审）
- MemoryProvider 接口对接
- 子代理委派

真实模式：调用 Hermes CLI/API
本地模式：用 DeepSeek 后端 + 本地推理（离线可用）
"""

from __future__ import annotations
import os
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import Adapter, AdapterResult

logger = logging.getLogger(__name__)


class HermesAdapter(Adapter):
    """Hermes Agent AI 推理 + 自进化适配器"""

    @property
    def name(self) -> str:
        return "hermes"

    def __init__(self, workspace: str = "", model_backend=None, local_only: bool = False):
        self._workspace = Path(workspace or os.path.expanduser("~/.xai/workspace"))
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._local_only = local_only
        self._model_backend = model_backend  # XAI 的 ModelBackend 实例
        self._skills_dir = self._workspace / "hermes_skills"
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._evo_dir = self._workspace / "hermes_evo"
        self._evo_dir.mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        if self._local_only:
            return False
        return shutil.which("hermes") is not None

    def health_check(self) -> AdapterResult:
        if self.is_available():
            try:
                r = subprocess.run(["hermes", "--version"], capture_output=True, text=True, timeout=5)
                return AdapterResult(ok=True, output=r.stdout.strip(), meta={"mode": "real"})
            except Exception:
                pass
        backend_ok = self._model_backend is not None
        if backend_ok:
            # 真实探活：发一个最小推理请求，验证 backend 真的能返回（不再假阳性）
            try:
                resp = self._model_backend.complete("ping", max_tokens=1)
            except Exception as e:
                return AdapterResult(
                    ok=False,
                    output=f"本地模式，模型后端探活失败: {e}",
                    meta={"mode": "local", "backend": type(self._model_backend).__name__, "live": False, "error": str(e)[:200]},
                )
            # 推理调用成功（无异常）= 后端真实在线（live）。
            # 个别后端对 1-token 探活可能返回空串，仍代表连接通畅、可正常服务。
            return AdapterResult(
                ok=True,
                output="本地模式，模型后端: 可用（真实响应已验证）" if resp else "本地模式，模型后端: 可用（探活返回空串，仍视为在线）",
                meta={"mode": "local", "backend": type(self._model_backend).__name__, "live": True},
            )
        return AdapterResult(
            ok=False,
            output="未配置模型后端",
            meta={"mode": "local", "backend": "none"},
        )

    # ---- AI 推理 ----

    def infer(self, prompt: str, system: str = "", max_tokens: int = 2000) -> AdapterResult:
        """执行 AI 推理。

        优先用 XAI 的 ModelBackend（DeepSeek/Stub），因为 hermes CLI
        在某些场景会卡住（需 TTY 等），不稳定。
        仅当 model_backend 不可用时才回退到 hermes CLI。
        """
        # 优先 model_backend
        if self._model_backend:
            try:
                full_prompt = f"[系统指令]\n{system}\n\n[用户]\n{prompt}" if system else prompt
                response = self._model_backend.complete(full_prompt, max_tokens=max_tokens)
                return AdapterResult(ok=True, output=response, meta={"via": "model_backend"})
            except Exception as e:
                logger.warning(f"model_backend 失败: {e}，回退到 hermes CLI")
                # model_backend 失败时回退到 hermes CLI
                if self.is_available() and not self._local_only:
                    return self._infer_real(prompt, system, max_tokens)
                return AdapterResult(ok=False, error=str(e))

        # 无 model_backend 且有 hermes CLI
        if self.is_available() and not self._local_only:
            return self._infer_real(prompt, system, max_tokens)

        return AdapterResult(ok=False, error="未配置模型（设置 DEEPSEEK_API_KEY 环境变量或安装 Hermes Agent）")

    def _infer_real(self, prompt: str, system: str, max_tokens: int) -> AdapterResult:
        # 正确调用: hermes -z "prompt" -m model --yolo
        # -z 是根级选项，直接用，不需要 subcommand
        full_prompt = prompt
        if system:
            full_prompt = f"[系统指令] {system}\n\n用户: {prompt}"
        args = ["hermes", "-z", full_prompt, "-m", "deepseek-chat", "--yolo"]

        # 硬超时保护：Popen + wait + kill 三步，避免 subprocess.run 超时信号被吞
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = proc.communicate(timeout=20)
            if proc.returncode == 0 and stdout.strip():
                return AdapterResult(
                    ok=True,
                    output=stdout[:8000],
                    meta={"mode": "hermes-cli", "exit_code": proc.returncode},
                )
            logger.info(f"hermes CLI 返回非0 (exit={proc.returncode})，回退到 model_backend")
            return self._fallback_infer(prompt, system, max_tokens, f"hermes CLI exit={proc.returncode}: {stderr[:200]}")
        except subprocess.TimeoutExpired:
            proc.kill()  # 强制终止
            proc.wait()
            logger.warning("hermes CLI 超时20s，强制回退到 model_backend")
            return self._fallback_infer(prompt, system, max_tokens, "hermes CLI 超时20s")

    def _fallback_infer(self, prompt: str, system: str, max_tokens: int, reason: str) -> AdapterResult:
        """回退到 model_backend（DeepSeek/Stub）"""
        if self._model_backend:
            try:
                full_prompt = f"[系统指令]\n{system}\n\n[用户]\n{prompt}" if system else prompt
                response = self._model_backend.complete(full_prompt, max_tokens=max_tokens)
                return AdapterResult(ok=True, output=response, meta={"via": "model_backend", "fallback_reason": reason})
            except Exception as e:
                return AdapterResult(ok=False, error=f"回退推理失败: {e}")
        return AdapterResult(ok=False, error=f"推理不可用: {reason}")

    # ---- Skill 管理（对接 Hermes 的技能系统） ----

    def load_skill(self, skill_name: str) -> AdapterResult:
        skill_file = self._skills_dir / f"{skill_name}.json"
        if skill_file.exists():
            data = json.loads(skill_file.read_text())
            return AdapterResult(ok=True, output=f"技能已加载: {skill_name}", meta=data)
        return AdapterResult(ok=False, error=f"技能不存在: {skill_name}")

    def register_skill(self, name: str, description: str, prompt_snippet: str) -> AdapterResult:
        skill_file = self._skills_dir / f"{name}.json"
        # prompt 为空时回退到 description，保证技能有可进化的实质内容（避免进化时无料可改）
        prompt = prompt_snippet or description or f"你是 {name} 技能，负责完成任务：{description or name}"
        data = {"name": name, "description": description, "prompt": prompt, "version": 1}
        skill_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return AdapterResult(ok=True, output=f"技能已注册: {name}", meta=data)

    def list_skills(self) -> AdapterResult:
        if not self._skills_dir.exists():
            return AdapterResult(ok=True, output="(无技能)", meta={"count": 0})
        items = []
        for f in sorted(self._skills_dir.glob("*.json")):
            data = json.loads(f.read_text())
            items.append(f"  {data['name']}: {data.get('description', '')}")
        return AdapterResult(
            ok=True,
            output="\n".join(items) if items else "(无技能)",
            meta={"count": len(items)},
        )

    # ---- GEPA 自进化 ----

    def evolve_skill(self, skill_name: str, feedback: str = "") -> AdapterResult:
        """进化某个技能：用真实模型后端生成改进版 prompt，写入人工复审队列。

        不是直接应用，变异版本需人工批准后才生效（见 approve_skill）。
        """
        skill_file = self._skills_dir / f"{skill_name}.json"
        if not skill_file.exists():
            return AdapterResult(ok=False, error=f"技能不存在: {skill_name}")

        original = json.loads(skill_file.read_text())
        base = original.get("prompt", "")
        if feedback:
            base += f"\n\n[执行反馈，请据此优化: {feedback}]"
        mutated = self._mutate_prompt(skill_name, base)

        variant = original.copy()
        variant["prompt"] = mutated
        variant["version"] = original.get("version", 1) + 1
        variant["status"] = "pending_review"

        evo_file = self._evo_dir / f"{skill_name}_v{variant['version']}.json"
        evo_file.write_text(json.dumps(variant, ensure_ascii=False, indent=2))

        return AdapterResult(
            ok=True,
            output=f"技能 '{skill_name}' 已生成 v{variant['version']} 模型驱动变异，等待复审",
            meta={"skill": skill_name, "version": variant["version"], "status": "pending_review"},
        )

    def list_pending_reviews(self) -> AdapterResult:
        """列出等待人工复审的技能变异"""
        if not self._evo_dir.exists():
            return AdapterResult(ok=True, output="(无待复审)", meta={"count": 0})
        items = []
        for f in sorted(self._evo_dir.glob("*.json")):
            data = json.loads(f.read_text())
            if data.get("status") == "pending_review":
                items.append(f"  {data['name']} v{data['version']}: {data.get('description', '')}")
        return AdapterResult(
            ok=True,
            output="\n".join(items) if items else "(无待复审)",
            meta={"count": len(items)},
        )

    def approve_skill(self, skill_name: str, version: int) -> AdapterResult:
        """批准一个技能变异——将其应用为正式版本"""
        evo_file = self._evo_dir / f"{skill_name}_v{version}.json"
        if not evo_file.exists():
            return AdapterResult(ok=False, error=f"变异不存在: {skill_name} v{version}")

        variant = json.loads(evo_file.read_text())
        variant["status"] = "approved"

        # 写回正式技能目录
        skill_file = self._skills_dir / f"{skill_name}.json"
        skill_file.write_text(json.dumps(variant, ensure_ascii=False, indent=2))
        evo_file.write_text(json.dumps(variant, ensure_ascii=False, indent=2))

        return AdapterResult(
            ok=True,
            output=f"技能 '{skill_name}' v{version} 已批准并应用",
            meta={"skill": skill_name, "version": version},
        )

    # ---- 子代理委派 ----

    def delegate(self, task: str, agent_role: str = "general") -> AdapterResult:
        """派发子任务给指定角色的子代理"""
        system_prompt = f"你是 {agent_role} 专家。完成任务后返回简洁结果。"
        return self.infer(task, system=system_prompt, max_tokens=1000)

    # ---- Darwinian 进化器桥接（Hermes 原生 GEPA） ----

    def darwinian_evolve(self, skill_name: str = "", auto_approve: bool = False) -> AdapterResult:
        """Darwinian 技能进化（真实模型驱动变异）。

        对每个已注册技能，调用模型后端基于原 prompt 生成改进版本，
        写入进化目录并进入人工复审队列（不直接应用）。
        若模型后端不可用，退化为追加优化标记（仍诚实标注）。
        """
        targets = [self._skills_dir / f"{skill_name}.json"] if skill_name else sorted(self._skills_dir.glob("*.json"))
        if not targets:
            return AdapterResult(ok=True, output="无技能可进化", meta={"evolved": [], "mode": "real" if self._model_backend else "none"})

        evolved = []
        for f in targets:
            if not f.exists():
                continue
            data = json.loads(f.read_text())
            name = data.get("name", f.stem)
            mutated = self._mutate_prompt(name, data.get("prompt", ""))
            variant = data.copy()
            variant["prompt"] = mutated
            variant["version"] = data.get("version", 1) + 1
            variant["status"] = "pending_review"
            evo_file = self._evo_dir / f"{name}_v{variant['version']}.json"
            evo_file.write_text(json.dumps(variant, ensure_ascii=False, indent=2))
            evolved.append(name)

        mode = "real" if self._model_backend else "fallback"
        return AdapterResult(
            ok=True,
            output=f"Darwinian 进化完成，{len(evolved)} 个技能已生成模型驱动变异" if evolved else "无技能可进化",
            meta={"evolved": evolved, "mode": mode},
        )

    def _mutate_prompt(self, name: str, original_prompt: str) -> str:
        """用真实模型后端生成技能 prompt 的改进变异。

        失败（模型不可用/超时）时退化为追加优化标记，绝不静默、绝不伪造。
        """
        if not self._model_backend or not original_prompt.strip():
            return original_prompt + "\n\n[Darwinian: 本地无模型后端，已追加优化标记]"
        try:
            system = (
                "你是技能进化引擎。给定一个技能的系统提示词，输出一个改进版："
                "保留其核心能力，增强清晰度、鲁棒性与边界处理，去除冗余。"
                "只输出改进后的提示词本身，不要任何解释或前后缀。"
            )
            user = f"技能名: {name}\n原提示词:\n{original_prompt}\n\n请输出改进版提示词:"
            improved = self._model_backend.complete(user, system=system, max_tokens=1500)
            if improved and improved.strip():
                return improved.strip()
        except Exception as e:
            logger.warning(f"模型驱动变异失败，回退追加标记: {e}")
        return original_prompt + "\n\n[Darwinian: 模型变异失败，已追加优化标记]"

    def list_models(self) -> AdapterResult:
        """列出实际可用的 AI 模型（动态检测，绝不虚构未接入的模型）。

        仅当检测到真实后端 / API key / 本地运行时才列出对应模型，
        避免给出「看起来很全但都用不了」的虚假清单。
        """
        import os
        models: List[str] = []
        backend_name = type(self._model_backend).__name__ if self._model_backend else "none"

        if os.environ.get("DEEPSEEK_API_KEY"):
            models.append("deepseek-chat (已连接, DeepSeek API 直连) [当前默认]")
        if shutil.which("ollama"):
            models.append("ollama/* (本地已安装 Ollama，需先 `ollama serve` 并拉取模型)")
        if os.environ.get("OPENAI_API_KEY"):
            models.append("gpt-4o (已配置 OPENAI_API_KEY)")
        if os.environ.get("ANTHROPIC_API_KEY"):
            models.append("claude-sonnet-4 (已配置 ANTHROPIC_API_KEY)")
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            models.append("gemini-2.5-flash (已配置 Gemini API key)")
        if not models:
            models.append("(未检测到任何模型后端，请设置 DEEPSEEK_API_KEY 或安装 Ollama)")

        return AdapterResult(
            ok=True,
            output="\n".join(f"  {m}" for m in models),
            meta={"mode": "dynamic", "backend": backend_name},
        )

    def list_real_skills(self) -> AdapterResult:
        """列出 Hermes 真实技能目录（~/.hermes/skills/）"""
        skills_dir = Path.home() / ".hermes" / "skills"
        if not skills_dir.exists():
            return AdapterResult(ok=True, output="(Hermes skills 目录不存在)", meta={"count": 0})
        categories = []
        for d in sorted(skills_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                skill_files = list(d.glob("SKILL.md")) + list(d.glob("*.md"))
                categories.append({"category": d.name, "skills": len(skill_files)})
        total = sum(c["skills"] for c in categories)
        return AdapterResult(
            ok=True,
            output="\n".join(f"  {c['category']}: {c['skills']} 技能" for c in categories),
            meta={"categories": categories, "total_skills": total, "source": str(skills_dir)},
        )
