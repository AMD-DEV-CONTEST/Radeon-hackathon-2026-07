"""
🎨 绘图执行 Agent —— 文生图 & 图片编辑。

支持多种后端（按优先级降级）：
  1. API 生图（DALL-E / SiliconFlow SD / 其他 OpenAI 兼容服务）
  2. SD WebUI / Forge API（与 ComfyUI 并列的本地推理选项）
  3. 本地 ComfyUI + NoobAI（回退方案）

图片编辑流程:
  1. 视觉分析 → 描述原图
  2. LLM 增强 → 合并描述 + 编辑指令，生成新 prompt
  3. 文生图 → 根据增强 prompt 生成编辑后图片
"""
import asyncio
import glob as _glob
import os
import re as _re
import subprocess
import sys
import time
from pathlib import Path

from ..orchestration.executor import register_agent
from ..orchestration.dag import NodeType
from ..api.image_gen import generate, download_image
from ..api.llm import chat
from ..api.vision import analyze
from ..config import get_config
from loguru import logger


# ═══════════════════════════════════════════════
# 文生图
# ═══════════════════════════════════════════════

@register_agent(NodeType.IMAGE_GEN)
async def execute_image_gen(node, prompt: str, context: dict) -> str:
    logger.info(f"[IMG] [{node.id}] {prompt[:80]}...")
    logger.info(f"[TRACE-IMG] [{node.id}] 原prompt ({len(prompt)}c): {prompt[:300]}")

    # ── 检测：prompt 是执行指令而非视觉描述 ──
    cn_instruction_kw = ["读取", "使用", "根据", "请将", "生成以下", "JSON", "json",
                         "字段", "文件", "路径", "保存为", "记录", "确保生成", "前序节点"]
    en_instruction_kw = ["read the", "json file", "previous node", "output of",
                         "generate the following", "save as", "file at"]
    has_cn_instr = any(kw in prompt for kw in cn_instruction_kw)
    has_en_instr = any(kw.lower() in prompt.lower() for kw in en_instruction_kw)
    is_short = len(prompt) < 60 and _contains_chinese(prompt)
    is_instruction = has_cn_instr or has_en_instr or is_short

    if is_instruction and _contains_chinese(prompt):
        logger.warning(f"[IMG] [{node.id}] prompt 看起来是执行指令而非视觉描述，尝试提取画面内容")
        try:
            prompt = await asyncio.to_thread(_extract_visual_prompt, prompt)
            logger.info(f"[TRACE-IMG] [{node.id}] 指令→视觉描述 ({len(prompt)}c): {prompt[:300]}")
        except Exception as e:
            logger.warning(f"[IMG] [{node.id}] 视觉提取失败: {e}")

    if _contains_chinese(prompt):
        try:
            prompt = await asyncio.to_thread(_translate_to_image_prompt, prompt)
            logger.info(f"[TRACE-IMG] [{node.id}] 翻译后 ({len(prompt)}c): {prompt[:300]}")
        except Exception as e:
            logger.warning(f"[IMG] 翻译失败，使用原 prompt: {e}")
    else:
        logger.info(f"[TRACE-IMG] [{node.id}] 已是英文，跳过翻译")

    # ── 后端 1: API 生图（DALL-E / SiliconFlow SD 等） ──
    try:
        urls = await asyncio.to_thread(generate, prompt=prompt)
        if urls:
            output_dir = Path(get_config().settings.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(output_dir / f"image_{node.id}.png")
            await asyncio.to_thread(download_image, urls[0], output_path)
            logger.debug(f"[IMG] [{node.id}] → {output_path} (API)")
            return output_path
        logger.warning(f"[IMG] [{node.id}] API 生图返回空结果，尝试 SD WebUI")
    except Exception as e:
        # 鉴权/配额/配置错误是永久性的，不应尝试其他后端
        from ..api.errors import is_permanent_error
        if is_permanent_error(str(e)):
            logger.error(f"[IMG] API 生图永久性失败（不尝试 fallback）: {e}")
            return f"[WARN] API 生图失败: {e}"
        logger.warning(f"[IMG] API 生图失败: {e}，尝试 SD WebUI...")

    # ── 后端 2: SD WebUI / Forge API ──
    try:
        result = await _generate_sdwebui(node.id, prompt)
        if result and not result.startswith("[WARN]"):
            logger.info(f"[IMG] [{node.id}] → {result} (SD WebUI)")
            return result
    except Exception as e:
        logger.warning(f"[IMG] SD WebUI 失败: {e}，尝试 ComfyUI...")

    # ── 后端 3: 本地 ComfyUI + NoobAI ──
    return await _generate_local(node.id, prompt)


# ═══════════════════════════════════════════════
# 后端: SD WebUI / Forge API
# ═══════════════════════════════════════════════

async def _generate_sdwebui(node_id: str, prompt: str) -> str:
    """
    通过 Stable Diffusion WebUI / Forge API 生成图片。

    需要设置环境变量:
      SDWEBUI_URL=http://127.0.0.1:7860  (SD WebUI 地址)
    """
    sd_url = os.environ.get("SDWEBUI_URL", "")
    if not sd_url:
        return "[WARN] SD WebUI 未配置（设置 SDWEBUI_URL 环境变量）"

    import httpx

    sd_url = sd_url.rstrip("/")
    payload = {
        "prompt": f"masterpiece, best quality, {prompt}",
        "negative_prompt": "worst quality, low quality, normal quality, bad anatomy, watermark, text, signature",
        "steps": 25,
        "cfg_scale": 7,
        "width": 832,
        "height": 1216,
        "sampler_name": "DPM++ 2M SDE",
        "scheduler": "Karras",
    }

    logger.info(f"[IMG-SD] [{node_id}] prompt={prompt[:100]}...")

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            # txt2img
            resp = await client.post(f"{sd_url}/sdapi/v1/txt2img", json=payload)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("images"):
                return "[WARN] SD WebUI 返回空结果"

            # 解码并保存
            import base64
            output_dir = Path(get_config().settings.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(output_dir / f"image_{node_id}.png")

            img_data = base64.b64decode(data["images"][0])
            with open(output_path, "wb") as f:
                f.write(img_data)

            logger.info(f"[IMG-SD] [{node_id}] → {output_path}")
            return output_path
    except Exception as e:
        logger.warning(f"[IMG-SD] [{node_id}] 失败: {e}")
        raise


# ═══════════════════════════════════════════════
# 后端: ComfyUI + NoobAI
# ═══════════════════════════════════════════════

async def _generate_local(node_id: str, prompt: str) -> str:
    """使用本地 ComfyUI + NoobAI 生成图片（路径和参数从 config 读取）。

    ComfyUI 是异步队列模式，subprocess 返回后图片可能尚未写入。
    会轮询等待输出文件出现（最长等 120s）。
    """
    s = get_config().settings

    safe_id = "".join(c for c in node_id if c.isalnum() or c in "_-")[:20]
    script = s.comfyui_script
    prefix = f"agent_{safe_id}"
    output_dir = s.comfyui_output_dir

    t0 = time.time()
    candidates: list[str] = []  # 初始化防止 UnboundLocalError

    python_exe = sys.executable or "python"
    cmd = [
        python_exe, script, prompt,
        "--size", s.comfyui_default_size,
        "--cfg", str(s.comfyui_default_cfg),
        "--steps", str(s.comfyui_default_steps),
        "--prefix", prefix,
    ]
    logger.info(f"[IMG-LOCAL] [{node_id}] rp_gen prefix={prefix} prompt={prompt[:100]}...")
    try:
        # C1 修复：子进程放到线程池，避免阻塞事件循环（否则节点超时/Stop 无法生效）
        result = await asyncio.to_thread(
            subprocess.run,
            cmd, capture_output=True, text=True,
            timeout=s.comfyui_timeout, cwd=s.comfyui_work_dir,
        )
        # 检查 stdout/stderr 中是否有输出路径
        # 跨平台路径匹配：Windows (C:\...) 和 Unix (/path/...)
        # D2 修复：路径字符限定为 \w . - / 等，避免吞掉 Python repr 的尾巴（'] 等）
        output_lines = result.stdout + result.stderr
        path_matches = _re.findall(r"[A-Za-z]:[\\/][\w.\-\\/]+\.png", output_lines)
        if not path_matches:
            path_matches = _re.findall(r"/(?:[\w.\-]+/)*[\w.\-]+\.png", output_lines)
        # 验证匹配路径是否实际存在
        found_paths = [p for p in path_matches if os.path.isfile(p)]
        if found_paths:
            path = found_paths[-1]
            logger.info(f"[IMG-LOCAL] [{node_id}] → {path} (from stdout)")
            return path

        # ComfyUI 异步队列：轮询等待输出文件（D3：超时从配置读取，默认 300s）
        poll_timeout = s.comfyui_timeout
        poll_interval = 3
        waited = 0
        while waited < poll_timeout:
            await asyncio.sleep(poll_interval)
            waited += poll_interval
            candidates = []
            for f in _glob.glob(os.path.join(output_dir, f"{prefix}*.png")):
                if os.path.getmtime(f) >= t0 - 2:
                    candidates.append(f)
            if candidates:
                break
            logger.debug(f"[IMG-LOCAL] [{node_id}] 等待 ComfyUI 输出... ({waited}s)")

        if candidates:
            path = max(candidates, key=os.path.getmtime)
            logger.info(f"[IMG-LOCAL] [{node_id}] → {path} (waited {waited}s)")
            return path
        return f"[WARN] 生图完成但未找到输出 (等了 {poll_timeout}s)\nstdout:{result.stdout[-200:]}"
    except subprocess.TimeoutExpired:
        return f"[WARN] 本地生图超时 (>{s.comfyui_timeout}s)"
    except Exception as e:
        return f"[WARN] 本地生图失败: {e}"


# ═══════════════════════════════════════════════
# 图片编辑
# ═══════════════════════════════════════════════

EDIT_ENHANCER_SYSTEM = """你是一个专业的 AI 图片编辑 prompt 工程师。

你会收到：
1. 原图的详细描述（视觉模型分析的结果）
2. 用户的编辑需求

你的任务是将两者合并为一条高质量的英文生图 prompt，用于重新生成编辑后的图片。

要求：
- 保留原图的构图、主体、风格描述
- 根据编辑需求精确修改对应元素
- 加入画质关键词（highly detailed, 4k, masterpiece, professional）
- 直接输出英文 prompt，不要任何解释或标记"""


@register_agent(NodeType.IMAGE_EDIT)
async def execute_image_edit(node, prompt: str, context: dict) -> str:
    logger.info(f"[EDIT] [{node.id}] {prompt[:80]}...")

    # Step 1: 定位源图片
    image_path = _find_source_image(node, context)
    if not image_path:
        return "[WARN] 图片编辑需要源图片。请先上传图片，或确保前置节点生成了图片。"

    logger.debug(f"[EDIT] 源图片: {image_path}")

    # Step 2: 视觉分析 — 描述原图
    logger.info(f"[EDIT] 正在分析原图...")
    try:
        description = await asyncio.to_thread(
            analyze,
            image_path=image_path,
            prompt="请详细描述这张图片的内容：主体是什么、什么风格（写实/插画/3D/像素等）、"
                   "构图方式（特写/全景/对称等）、主要色彩和光影、画面中的关键元素和细节。"
                   "用中文描述，尽量详细。",
        )
        logger.debug(f"[EDIT] 原图描述: {description[:150]}...")
    except Exception as e:
        logger.error(f"[EDIT] 视觉分析失败: {e}")
        return f"[WARN] 无法分析原图: {e}"

    # Step 3: LLM 增强 — 合并描述 + 编辑指令 → 新 prompt
    logger.info(f"[EDIT] 正在合成编辑 prompt...")
    try:
        s = get_config().settings
        enhanced = await asyncio.to_thread(
            chat,
            messages=[
                {"role": "system", "content": EDIT_ENHANCER_SYSTEM},
                {"role": "user", "content": (
                    f"原图描述：\n{description}\n\n"
                    f"编辑需求：\n{prompt}"
                )},
            ],
            temperature=s.editor_temperature,
            max_tokens=s.editor_max_tokens,
        )
        enhanced = enhanced.strip()
        logger.debug(f"[EDIT] 增强 prompt: {enhanced[:150]}...")
    except Exception as e:
        logger.error(f"[EDIT] prompt 增强失败: {e}")
        if _contains_chinese(prompt):
            try:
                enhanced = await asyncio.to_thread(_translate_to_image_prompt, prompt)
            except Exception:
                return f"[WARN] 无法生成编辑 prompt: {e}"
        else:
            return f"[WARN] 无法生成编辑 prompt: {e}"

    # Step 4: 文生图
    logger.info(f"[EDIT] 正在生成编辑后图片...")
    try:
        urls = await asyncio.to_thread(generate, prompt=enhanced)
        if not urls:
            return "[WARN] 图片编辑生成失败，未返回结果。"
    except Exception as e:
        logger.error(f"[EDIT] 生图失败: {e}")
        return f"[WARN] 图片编辑生成失败: {e}"

    # Step 5: 保存结果
    output_dir = Path(get_config().settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / f"edited_{node.id}.png")

    await asyncio.to_thread(download_image, urls[0], output_path)
    logger.info(f"[EDIT] [{node.id}] → {output_path}")
    return output_path


# ═══════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════

def _find_source_image(node, context: dict) -> str | None:
    """从上下文或依赖节点中查找源图片。"""
    # 优先：用户直接上传的图片
    image_path = context.get("_user_image")
    if image_path and os.path.isfile(str(image_path)):
        return str(image_path)

    # 其次：依赖节点生成的图片
    for dep_id in node.depends_on:
        dep_result = context.get(dep_id)
        if dep_result and isinstance(dep_result, str):
            p = str(dep_result)
            if os.path.isfile(p) and Path(p).suffix.lower() in (
                ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"
            ):
                return p

    # 最后：用户上传的图片 URL
    image_url = context.get("_user_image_url")
    if image_url:
        return str(image_url)

    return None


def _contains_chinese(text: str) -> bool:
    return any('一' <= char <= '鿿' for char in text)


def _extract_visual_prompt(instruction: str) -> str:
    """从执行指令中提取视觉描述——当 Planner 误把指令发给 image_gen 时兜底。"""
    messages = [
        {
            "role": "system",
            "content": (
                "你收到一段可能是'执行指令'的文本，你的任务是：\n"
                "1. 判断其中是否包含需要绘制的画面描述\n"
                "2. 如果有，提取/归纳为 NoobAI 标签格式（逗号分隔的英文标签）\n"
                "3. 如果没有任何画面描述，基于指令中的角色/场景关键词编一个合理的标签序列\n"
                "4. 前面加 very awa, masterpiece, best quality, newest, highres, absurdres\n"
                "5. 只输出标签序列，不要任务指令、不要 JSON、不要说明文字"
            ),
        },
        {"role": "user", "content": instruction[:2000]},
    ]
    result = chat(messages, temperature=0.3, max_tokens=512).strip()
    # 清理可能的 markdown/json 包裹
    m = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", result, _re.DOTALL)
    if m:
        result = m.group(1).strip()
    # 绝不返回空：如果 LLM 返回空，从指令中提取关键词作为兜底
    if not result:
        cn_match = _re.search(r'[一-鿿]{4,}', instruction)
        en_match = _re.search(
            r'(?:anime|girl|boy|school|uniform|blue|pink|hair|illustration)[^,.]*',
            instruction, _re.IGNORECASE,
        )
        fallback = (cn_match.group(0) if cn_match else "") + " " + (en_match.group(0) if en_match else "")
        result = fallback.strip() or "anime style illustration, highly detailed"
        logger.warning(f"[IMG] _extract_visual_prompt 返回空，使用兜底: {result[:100]}")
    return result


def _translate_to_image_prompt(chinese_text: str) -> str:
    s = get_config().settings
    messages = [
        {
            "role": "system",
            "content": (
                "你是一个 NoobAI / Illustrious XL 模型的 prompt 工程师。\n"
                "将用户的中文描述转化为 NoobAI 标签格式的英文 prompt。\n\n"
                "## 格式规则（必须遵守）\n"
                "1. 使用逗号分隔的标签（tags），不是自然语言句子\n"
                "2. 标签中不要有下划线'_'，用空格替代\n"
                "3. 质量标签放前面：very awa, masterpiece, best quality, newest, highres, absurdres\n"
                "4. 角色格式：角色名 \\(作品名\\), 作品名 （例如 ganyu \\(genshin impact\\), genshin impact）\n"
                "5. 标签顺序：1girl/1boy → 角色 → 系列 → 外貌特征 → 场景 → 光影 → 氛围\n"
                "6. 外貌特征优先使用 Danbooru 标准标签（如 very long hair, pink hair, ahoge, heterochromia）\n\n"
                "## 重要\n"
                "严格按照用户输入中的角色和画面描述生成标签。"
                "除非用户明确提到该角色，否则不要套用任何预设角色的外貌特征。\n"
                "若用户提到作品角色（如 azusa/梓/star 等），先识别其所属作品并转换为标准标签，"
                "如 azusa (blue archive)、hoshino (blue archive)，再按角色真实特征补充标签。\n"
                "直接输出标签序列，不要解释。"
            ),
        },
        {"role": "user", "content": chinese_text},
    ]
    return chat(messages, temperature=s.translator_temperature,
                max_tokens=s.translator_max_tokens).strip()
