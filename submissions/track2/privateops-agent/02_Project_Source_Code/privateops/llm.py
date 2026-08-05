from __future__ import annotations

import json
import os
import urllib.request

from privateops.config import validate_model_endpoint
from privateops.models import Evidence


class DeterministicProvider:
    name = "deterministic-local"

    def complete(
        self,
        prompt: str,
        evidence: list[Evidence],
        memory: dict[str, str],
        execution_context: dict[str, object] | None = None,
    ) -> str:
        use_chinese = prompt.rstrip().endswith("请用中文回答。")
        if evidence:
            basis = evidence[0].snippet
        else:
            successful_tools = [
                item for item in (execution_context or {}).get("tool_results", [])
                if isinstance(item, dict) and item.get("status") in {"completed", "attention"}
            ]
            if successful_tools:
                details = []
                for item in successful_tools:
                    count = item.get("output", {}).get("count")
                    detail = str(item.get("name", "local_tool"))
                    if count is not None:
                        detail += f" ({count})"
                    details.append(detail)
                joined = ", ".join(details)
                basis = (
                    f"已取得并使用本地工具结果：{joined}。"
                    if use_chinese
                    else f"Local tool observations were collected and used: {joined}."
                )
            else:
                basis = "未找到匹配的本地证据。" if use_chinese else "No matching local evidence was found."
        memory_hint = ""
        if memory:
            saved_memory = "; ".join(f"{key}={value}" for key, value in sorted(memory.items()))
            memory_hint = (
                f" 我还参考了已保存的本地记忆：{saved_memory}"
                if use_chinese
                else f" I also considered saved local memory: {saved_memory}"
            )
        if use_chinese:
            return (
                f"PrivateOps 回答：根据本地证据：{basis} "
                "该回答会展示证据、权限状态和本地记忆，便于审核。"
                f"{memory_hint}"
            )
        return (
            "PrivateOps answer: "
            f"{basis} "
            "The response keeps evidence, permission state, and local memory visible for review."
            f"{memory_hint}"
        )


class OpenAICompatibleProvider:
    name = "openai-compatible-rocm"

    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int = 90,
        allow_remote: bool = False,
    ):
        self.name = "openai-compatible-amd-cloud" if allow_remote else "openai-compatible-rocm"
        self.endpoint = validate_model_endpoint(
            endpoint or os.environ.get("PRIVATEOPS_MODEL_ENDPOINT", ""),
            allow_remote=allow_remote,
        )
        self.model = model or os.environ.get("PRIVATEOPS_MODEL_NAME", "local-rocm-model")
        self.api_key = api_key if api_key is not None else os.environ.get("PRIVATEOPS_MODEL_API_KEY", "")
        self.timeout = timeout

    def complete(
        self,
        prompt: str,
        evidence: list[Evidence],
        memory: dict[str, str],
        execution_context: dict[str, object] | None = None,
    ) -> str:
        if not self.endpoint:
            return DeterministicProvider().complete(prompt, evidence, memory)
        context = "\n".join(f"[{item.source}] {item.snippet}" for item in evidence)
        execution = execution_context or {}
        system_tool_names = {
            "startup_inventory",
            "process_inventory",
            "service_inventory",
            "scheduled_task_inventory",
            "system_overview",
            "network_listener_inventory",
            "security_status",
        }
        has_system_observations = any(
            isinstance(item, dict) and item.get("name") in system_tool_names
            for item in execution.get("tool_results", [])
        )
        inspection_rules = ""
        if has_system_observations:
            inspection_rules = (
                "\n\nMandatory system-inspection response rules:\n"
                "- Report only fields present in successful tool results.\n"
                "- Do not add a purpose, identity, safety, or risk description for individual software entries.\n"
                "- State once that software purpose and safety were not verified.\n"
                "- Do not claim completeness beyond the named data sources."
            )
        use_chinese = prompt.rstrip().endswith("请用中文回答。")
        system_language_rule = ""
        language_rule = ""
        if use_chinese:
            system_language_rule = "你必须只用简体中文回答，不得使用英文。\n\n"
            language_rule = (
                "\n\nMandatory output language: Respond entirely in Simplified Chinese."
            )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{system_language_rule}You are PrivateOps Agent. Prefer supplied local evidence as private context, "
                        "but use general knowledge and reasoning when it is insufficient. Clearly disclose "
                        "missing private evidence and uncertainty. Observed tool results are facts; general "
                        "knowledge is advice and must be labeled separately. Never claim that this computer "
                        "was inspected or that an operation ran unless a successful allowed tool result proves it. "
                        "Do not infer missing or hidden items from a bounded inventory. Do not guess software purpose "
                        "or safety from its name; label identity and risk as unknown unless observed evidence proves them."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {prompt}\n\nEvidence:\n{context or '(none)'}"
                        f"\n\nMemory:\n{json.dumps(memory, ensure_ascii=False)}"
                        f"\n\nExecution context:\n{json.dumps(execution, ensure_ascii=False)}"
                        f"{inspection_rules}{language_rule}"
                    ),
                },
            ],
            "temperature": 0.2,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.endpoint,
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw_response = response.read().decode("utf-8")
        try:
            result = json.loads(raw_response)
            content = result["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty content")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise OSError("Model provider returned an invalid completion.") from exc
        return content.strip()
