from __future__ import annotations

from enum import Enum
import json

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel


class PromptId(str, Enum):
    SCHEDULER_FEEDBACK_SUMMARY = "scheduler.feedback.summary"


def get_prompt(prompt_id: PromptId) -> ChatPromptTemplate:
    if prompt_id == PromptId.SCHEDULER_FEEDBACK_SUMMARY:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的定时任务完成事件总结器。\n"
                    "你只根据输入的 SchedulerExecutionReport 事实生成完成事件摘要。\n"
                    "不要调用工具，不要重新执行任务，不要补充未出现在事实里的内容。\n"
                    "不要把摘要写成普通对话，也不要要求用户确认。\n"
                    "如果 report.stdout_preview 有内容，优先把它作为本次任务的业务结果来总结。\n"
                    "不要只说“工具执行完成”或“退出码为 0”，除非没有任何 stdout/output 可用。\n"
                    "run.completed_count 表示这个定时任务累计第几次完成，不是本次完成了多少项操作。\n"
                    "失败或跳过时，优先使用 report.error_summary 和 report.stderr_preview 说明原因。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "输出字段：\n"
                    "- summary: 面向用户展示的中文摘要，可以包含任务结果、失败原因或跳过原因。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "定时任务执行事实 JSON：\n{feedback_context}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    raise KeyError(f"unknown prompt id: {prompt_id}")


def output_json_schema(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2)
