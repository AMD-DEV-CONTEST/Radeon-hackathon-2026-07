"""
Layer 3: 生图工头（v2.0）

管理 1 个生图引擎（SD/即梦/NoobAI），负责：
- 提示词工程：将自然语言描述转化为生图专用 Prompt
- 参数封装：Prompt + 尺寸、数量等参数封包
- 策略缓存：优先命中缓存的 Prompt 模板
- 失败经验捕捉：因参数导致效果不佳时提炼写入经验记忆

对应第4层：1 个生图 Worker（通过 MCP 调用）
"""
from __future__ import annotations

import asyncio
from typing import Any
from loguru import logger

from .base_foreman import BaseForeman, Workspace
from ..layer4.mcp_contract import IMAGE_GEN_SCHEMA


class ImageForeman(BaseForeman):
    """
    生图工头 —— 管理一个生图引擎。

    策略缓存示例：
    - anime_style: 动漫风格模板
    - realistic: 写实风格模板
    - negative_prompt: 通用负向提示词
    """

    foreman_type = "image"

    def __init__(self):
        super().__init__()
        self.max_retries = 1
        self.base_timeout = IMAGE_GEN_SCHEMA.timeout_per_type

        # 策略缓存：Prompt 模板库
        self.set_cached_strategy("anime_style", (
            "{subject}, anime style, vibrant colors, masterpiece, best quality, "
            "absurdres, highres, detailed"
        ))
        self.set_cached_strategy("realistic", (
            "{subject}, photorealistic, 8k, detailed, sharp focus, "
            "professional lighting, high quality"
        ))
        self.set_cached_strategy("watercolor", (
            "{subject}, traditional watercolor painting, soft edges, "
            "paper texture, artistic, beautiful"
        ))
        self.set_cached_strategy("negative_default", (
            "bad anatomy, blurry, distorted, low quality, worst quality, "
            "extra fingers, mutated hands, ugly, jpeg artifacts"
        ))

        # 风格关键词映射（用于自动选择模板）
        self._style_keywords = {
            "anime_style": ["动漫", "二次元", "anime", "日系", "漫画", "卡通", "cartoon"],
            "realistic": ["写实", "真实", "照片", "photorealistic", "realistic", "真人"],
            "watercolor": ["水墨", "水彩", "watercolor", "国画", "工笔", "写意"],
        }

    # ── 执行入口 ──

    async def _execute_impl(self, task: dict, ws: Workspace) -> str:
        """生图工头执行逻辑。"""
        user_input = self._sanitize_input(task.get("user_input", ""))
        task_id = task.get("task_id", "")

        # 1. 检测风格 → 命中策略缓存
        style_key = self._detect_style(user_input)
        subject = self._extract_subject(user_input)

        # 2. 生成生图专用 Prompt
        prompt = self._build_image_prompt(subject, style_key)
        negative = self.get_cached_strategy("negative_default") or ""

        # v3 P4: prompt 归一化（中文→NoobAI 标签；执行指令→视觉描述兜底）
        prompt = await self._normalize_image_prompt(prompt)

        # 3. 参数封装
        from ..config import get_config
        s = get_config().settings

        params = {
            "prompt": prompt,
            "negative_prompt": negative,
            "width": 832,
            "height": 1216,
            "cfg_scale": s.comfyui_default_cfg,
            "steps": s.comfyui_default_steps,
        }

        # 4. 调用第4层生图 Worker（三层降级）
        logger.info(f"[FM:image] [{task_id}] style={style_key}, prompt={prompt[:120]}...")

        # 生图可能是同步 subprocess 调用，用 to_thread 包装
        result = await self._call_image_worker(params, task_id)

        # 5. 更新工作区上下文
        ws.last_summary = f"生成图片: {subject[:50]} (style={style_key})"

        return result

    # ── 风格检测 ──

    def _detect_style(self, user_input: str) -> str:
        """从用户输入中检测风格关键词，返回策略缓存键。"""
        input_lower = user_input.lower()
        for style_key, keywords in self._style_keywords.items():
            if any(kw in input_lower for kw in keywords):
                return style_key
        return "anime_style"  # 默认动漫风格

    def _extract_subject(self, user_input: str) -> str:
        """提取画面主体描述。"""
        # 简单策略：去掉明显的风格描述词
        style_noise = {
            "动漫风格", "写实风格", "水墨风格", "二次元", "水彩风格",
            "anime style", "realistic", "watercolor", "日系",
        }
        subject = user_input
        for noise in style_noise:
            subject = subject.replace(noise, "")
        return subject.strip().strip("，。,.") or user_input

    # ── Prompt 构建 ──

    def _build_image_prompt(self, subject: str, style_key: str) -> str:
        """构建生图专用 Prompt：填充策略缓存模板。"""
        template = self.get_cached_strategy(style_key)
        if not template:
            template = self.get_cached_strategy("anime_style")

        prompt = template.replace("{subject}", subject)

        # 星野(Hoshino)标准外貌标签自动注入
        if any(k in subject.lower() for k in ("星野", "hoshino", "hoshina")):
            hoshino_tags = (
                "very long pink hair, huge ahoge, heterochromia, "
                "blue eyes, yellow eyes, black plaid skirt, "
                "white collared shirt, chest harness, blue necktie"
            )
            prompt = f"{prompt}, {hoshino_tags}"
            logger.info("[FM:image] 注入星野外貌标签")

        return prompt

    # ── 第4层调用 ──

    async def _normalize_image_prompt(self, prompt: str) -> str:
        """v3 P4: prompt 归一化。

        - 若 prompt 疑似执行指令（非视觉描述）→ 用 LLM 提取视觉描述兜底
        - 若含中文 → 翻译为 NoobAI 标签格式
        """
        from ..agents.image_gen import (
            _contains_chinese, _extract_visual_prompt, _translate_to_image_prompt,
        )

        # 检测执行指令
        cn_instruction_kw = ["读取", "使用", "根据", "请将", "生成以下", "JSON", "json",
                             "字段", "文件", "路径", "保存为", "记录", "确保生成", "前序节点"]
        has_cn_instr = any(kw in prompt for kw in cn_instruction_kw)
        is_short = len(prompt) < 60 and _contains_chinese(prompt)

        if (has_cn_instr or is_short) and _contains_chinese(prompt):
            logger.warning(f"[FM:image] prompt 疑似执行指令，提取视觉描述")
            try:
                prompt = await asyncio.to_thread(_extract_visual_prompt, prompt)
            except Exception as e:
                logger.warning(f"[FM:image] 视觉提取失败: {e}")

        if _contains_chinese(prompt):
            try:
                prompt = await asyncio.to_thread(_translate_to_image_prompt, prompt)
            except Exception as e:
                logger.warning(f"[FM:image] 翻译失败，使用原 prompt: {e}")

        return prompt

    async def _call_image_worker(self, params: dict, task_id: str) -> str:
        """v3 P4: 调用生图 Worker —— 完整三层降级。

        后端顺序：API 生图 → SD WebUI/Forge → 本地 ComfyUI + NoobAI。
        """
        from ..agents.image_gen import _generate_sdwebui, _generate_local
        from ..api.image_gen import generate as api_generate, download_image
        from ..api.errors import is_permanent_error
        from pathlib import Path
        from ..config import get_config
        import time

        prompt = params["prompt"]
        size = f"{params['width']}x{params['height']}"

        # ── 后端 1: API 生图 ──
        try:
            urls = await asyncio.to_thread(api_generate, prompt=prompt, size=size)
            if urls:
                output_dir = Path(get_config().settings.output_dir) / "images"
                output_dir.mkdir(parents=True, exist_ok=True)
                local_path = str(output_dir / f"generated_{task_id}_{int(time.time())}.png")
                try:
                    await asyncio.to_thread(download_image, urls[0], local_path)
                    logger.info(f"[FM:image] [{task_id}] → {local_path} (API)")
                    return local_path
                except Exception as e:
                    logger.warning(f"[FM:image] 下载失败，返回 URL: {e}")
                    return urls[0]
        except Exception as e:
            # 鉴权/配额/配置错误是永久性的，不尝试其他后端
            if is_permanent_error(str(e)):
                logger.error(f"[FM:image] API 生图永久性失败（不尝试 fallback）: {e}")
                raise RuntimeError(f"API 生图失败: {e}") from e
            logger.warning(f"[FM:image] API 生图失败: {e}，尝试 SD WebUI...")

        # ── 后端 2: SD WebUI / Forge API ──
        try:
            result = await _generate_sdwebui(f"img_{task_id}", prompt)
            if result and not result.startswith("[WARN]"):
                logger.info(f"[FM:image] [{task_id}] → {result} (SD WebUI)")
                return result
        except Exception as e:
            logger.warning(f"[FM:image] SD WebUI 失败: {e}，尝试 ComfyUI...")

        # ── 后端 3: 本地 ComfyUI + NoobAI ──
        logger.info(f"[FM:image] [{task_id}] 回退本地 ComfyUI + NoobAI")
        result = await _generate_local(f"img_{task_id}", prompt)
        # 重构修复（Bug 5）：全链路失败时 _generate_local 返回 "[WARN] ..." 字符串，
        # 若不检查会被 base_foreman 包装成 success（用户看到 ✅ 但没有图片）。
        # 抛异常进入 error 分支，生图失败经验也能正常沉淀。
        if isinstance(result, str) and result.startswith("[WARN]"):
            raise RuntimeError(result)
        return result
