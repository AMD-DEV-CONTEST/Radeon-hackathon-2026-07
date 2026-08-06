# -*- coding: utf-8 -*-
"""
tools/ocr_tool.py — 发票多模态提取工具

复用现有 app.py 的 stream_model / parse_model_output 思路，扩展提示词以
额外提取药品明细 items 数组。核心函数 extract_invoice 可独立单测；
invoice_ocr_tool 为 LangChain @tool 封装。

底层调用 config.MODEL_URL（OpenAI 兼容端点，当前经 SSH 隧道指向 AMD/llama.cpp
上的 Qwen3.6-27B 多模态模型）。该模型为思维链模型，最终 JSON 在 content 中，
思考过程在 reasoning_content 中；解析时以 content 为主、reasoning_content 兜底。
"""

import os
import json
import base64

import requests
import urllib3
from langchain_core.tools import tool

import tools  # noqa: F401  注入 sys.path
import config as cfg

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


OCR_PROMPT = """请仔细识别这张中国医疗/药品发票，提取字段与药品明细。只返回 JSON（不要多余文字、不要解释、不要 markdown 代码块）：
{
  "fpdm": "发票代码（数电票留空）",
  "fphm": "发票号码",
  "date": "开票日期 yyyyMMdd",
  "code": "价税合计金额（纯数字，如 136.00）",
  "items": [
    {"name": "药品/项目名称", "spec": "规格（无则留空）", "amount": "数量（无则留空）", "priceSum": "该项金额（纯数字）"}
  ]
}
若无法识别药品明细，items 返回空数组 []。"""


def encode_image(image_path: str, max_width: int = None) -> str:
    """读取图片并 base64 编码；超过 max_width 时等比压缩以降低视觉编码耗时。"""
    max_width = max_width or cfg.IMAGE_MAX_WIDTH
    try:
        from PIL import Image
        import io

        with Image.open(image_path) as im:
            if im.width > max_width:
                ratio = max_width / float(im.width)
                new_size = (max_width, int(im.height * ratio))
                im = im.convert("RGB").resize(new_size)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=90)
                return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        # PIL 不可用或处理失败时，退回原图直接编码
        pass
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def parse_model_output(text: str):
    """从模型输出中提取首个完整 JSON 对象；去除 <think> 段与 markdown 代码围栏。"""
    if not text:
        return None
    # 去掉思维链标签包裹的内容（思维链模型可能把 <think>...</think> 混入 content）
    import re
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    cleaned = cleaned.replace("```json", "").replace("```", "")
    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1
        return json.loads(cleaned[start:end])
    except (ValueError, json.JSONDecodeError):
        return None


def _normalize_items(items):
    """规范化 items：确保为 list[dict]，priceSum/amount 尽量转数字。"""
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "")).strip()
        if not name:
            continue
        price = it.get("priceSum", it.get("price", ""))
        try:
            price = float(str(price).replace(",", "").replace("￥", "").replace("¥", ""))
        except (ValueError, TypeError):
            price = 0.0
        out.append({
            "name": name,
            "spec": str(it.get("spec", "")).strip(),
            "amount": str(it.get("amount", "")).strip(),
            "priceSum": price,
        })
    return out


def extract_invoice(image_path: str) -> dict:
    """调用多模态模型提取发票字段与药品明细。返回 dict（含 items）。"""
    if not image_path or not os.path.exists(image_path):
        return {"error": f"图片不存在: {image_path}", "items": []}

    b64 = encode_image(image_path)
    payload = {
        "model": cfg.MODEL_ID,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        "temperature": cfg.LLM_TEMPERATURE,
        "max_tokens": max(cfg.LLM_MAX_TOKENS, 2048),
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    try:
        resp = requests.post(cfg.MODEL_URL, json=payload, timeout=cfg.LLM_TIMEOUT, verify=False)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
    except Exception as e:
        return {"error": f"模型请求异常: {e}", "items": []}

    # 三重兑底：content → reasoning_content → 两者拼接（思维链模型 JSON 可能落在任一处）
    fields = parse_model_output(content) or parse_model_output(reasoning) \
        or parse_model_output(content + "\n" + reasoning)
    if not fields:
        tail = (content or reasoning)[-500:]
        return {"error": "模型未返回可解析的 JSON", "raw": tail, "items": []}

    fields["items"] = _normalize_items(fields.get("items", []))
    for k in ("fpdm", "fphm", "date", "code"):
        fields.setdefault(k, "")
    return fields


@tool
def invoice_ocr_tool(image_path: str) -> dict:
    """识别中国医疗/药品发票图片，提取发票代码(fpdm)、发票号码(fphm)、开票日期(date)、
    价税合计(code) 及药品明细列表(items，每项含 name/spec/amount/priceSum)。
    入参 image_path 为发票图片的本地文件路径。返回包含上述字段的 JSON 对象。"""
    return extract_invoice(image_path)
