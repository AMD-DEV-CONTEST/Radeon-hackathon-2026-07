"""自然语言 → DAG 生成（带稳健解析与严格重试）。

单一事实源：画布 `/api/canvas/validate` 与工作流 `/api/workflow/from_text`
共用这里的生成逻辑，避免两套 prompt / 两套解析各自腐化。

设计要点（2026-08-04）：
  - 解析用 core.json_extract.extract_dag（括号配对，字符串感知），
    不再用贪婪正则 `\\{[\\s\\S]*\\}`——后者遇到模型的推演前言必炸。
  - 第一次失败不直接 500，而是**换一条更严格的提示词重试一次**：
    实测 DeepSeek 类模型偶发用英文自述推演（"We need answer in Chinese? ..."），
    加一句"只输出 JSON，第一个字符必须是 {"后基本都能纠回来。
  - 两次都失败才诚实报错，并把原始输出回传，便于定位是模型问题而非代码问题。
"""

from __future__ import annotations

from typing import Optional

from core.json_extract import extract_dag

_STRICT_SUFFIX = (
    "\n\n【严格输出约束】只输出 JSON 本身，不要任何解释、前言、思考过程或 Markdown 围栏。"
    "响应的第一个字符必须是 {，最后一个字符必须是 }。"
)

_SYSTEM = "你是工作流设计师。你只输出 JSON，不输出任何自然语言解释。"


def generate_dag(engine, prompt: str, max_tokens: int = 1500) -> Optional[dict]:
    """调用模型生成 DAG，返回 {"nodes": [...], "edges": [...]} 或 None。"""
    last_raw = ""
    for attempt in range(2):
        p = prompt if attempt == 0 else (prompt + _STRICT_SUFFIX)
        try:
            result = engine._infer_with_fallback(prompt=p, system=_SYSTEM, max_tokens=max_tokens)
        except Exception:
            continue
        if not getattr(result, "ok", False):
            continue
        last_raw = (result.output or "").strip()
        dag = extract_dag(last_raw)
        if dag:
            return dag
    return None


def generate_dag_verbose(engine, prompt: str, max_tokens: int = 1500) -> tuple[Optional[dict], str]:
    """同 generate_dag，但额外返回最后一次模型原始输出（用于错误回传）。"""
    last_raw = ""
    for attempt in range(2):
        p = prompt if attempt == 0 else (prompt + _STRICT_SUFFIX)
        try:
            result = engine._infer_with_fallback(prompt=p, system=_SYSTEM, max_tokens=max_tokens)
        except Exception as e:
            last_raw = f"[调用异常] {e}"
            continue
        if not getattr(result, "ok", False):
            last_raw = getattr(result, "error", "") or "生成失败"
            continue
        last_raw = (result.output or "").strip()
        dag = extract_dag(last_raw)
        if dag:
            return dag, last_raw
    return None, last_raw
