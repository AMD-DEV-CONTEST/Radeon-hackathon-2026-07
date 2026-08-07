import logging
from typing import List, Dict, Any, Optional, Callable
from inference.engine import InferenceEngine
from memory.manager import MemoryManager
import tools  # noqa: F401  导入即触发所有工具注册到 registry
from tools.registry import registry
from tools.hardware_tools import set_engine  # 注入推理引擎给硬件生成工具
from .planner import Planner
from .executor import Executor
from .reflector import Reflector
from .audit import audit_logger
from .prompts import get_system_prompt

logger = logging.getLogger(__name__)


class RadeonAgent:
    def __init__(
        self,
        engine: InferenceEngine,
        memory_manager: Optional[MemoryManager] = None,
        max_iterations: int = 10,
        approval_callback: Optional[Callable] = None,
        prompt_mode: str = None,
    ):
        self.engine = engine
        self.memory_manager = memory_manager
        self.max_iterations = max_iterations
        self.planner = Planner(engine)
        self.executor = Executor(approval_callback=approval_callback)
        self.reflector = Reflector(engine)
        # system prompt 模式：hardware（默认，磐石硬件研发定位）/ generic（通用）
        self.prompt_mode = prompt_mode or "hardware"
        # 把推理引擎注入硬件生成工具（Verilog/Testbench），保持工具无状态契约
        set_engine(engine)

    def chat(self, message: str, use_rag: bool = True, prompt_mode: str = None,
             return_sources: bool = False):
        context = ""
        sources = []

        if self.memory_manager and use_rag:
            results = self.memory_manager.search(message)
            if results:
                context_parts = []
                for i, r in enumerate(results):
                    context_parts.append(f"[参考文档 {i + 1}]\n{r['content']}\n")
                    meta = r.get("metadata", {}) or {}
                    src = (
                        meta.get("source")
                        or meta.get("file_name")
                        or meta.get("file")
                        or f"document {i + 1}"
                    )
                    sources.append({"index": i + 1, "source": src, "content": r["content"]})
                context = "参考文档:\n" + "\n".join(context_parts)

        short_term_memory = self.memory_manager.get_short_term_memory() if self.memory_manager else []

        # system prompt 按模式切换：hardware（磐石硬件研发定位）/ generic（通用）
        system_prompt = get_system_prompt(prompt_mode or self.prompt_mode)

        messages = [{"role": "system", "content": system_prompt}]

        # 短期记忆按原始角色回填成真实多轮对话，交给 chat template 渲染，
        # 比拼成一段「role: content」文本更贴合指令模型的训练格式。
        for msg in short_term_memory[-5:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        # RAG 上下文与问题合并进同一轮 user 消息，避免出现连续多条 user turn
        if context:
            messages.append({"role": "user", "content": f"{context}\n\n问题 / Question:\n{message}"})
        else:
            messages.append({"role": "user", "content": message})

        response = self.engine.chat_completion(messages)

        if self.memory_manager:
            self.memory_manager.add_short_term_memory({"role": "user", "content": message})
            self.memory_manager.add_short_term_memory({"role": "assistant", "content": response})

        # 审计日志：记录对话（仅摘要，保护隐私）
        audit_logger.log_chat(message=message, response=response, used_rag=bool(context))

        if return_sources:
            return response, sources
        return response

    def run_task(self, task: str) -> Dict[str, Any]:
        logger.info(f"Starting task: {task}")
        
        tool_descriptions = registry.get_tool_descriptions()
        steps = self.planner.plan(task, tool_descriptions)
        
        if not steps:
            return {"success": False, "error": "任务规划失败"}
        
        logger.info(f"Generated {len(steps)} steps")
        
        results = []
        for step in steps:
            logger.info(f"Executing step {step.get('step')}: {step.get('description')}")
            
            result = self.executor.execute(step)
            results.append(result)
            
            if not result.get("success", False):
                logger.warning(f"Step {step.get('step')} failed")
                break

        reflection = self.reflector.reflect(task, steps, results)

        final_result = {
            "success": reflection.get("completed", False),
            "task": task,
            "steps": steps,
            "results": results,
            "reflection": reflection,
        }

        if self.memory_manager:
            self.memory_manager.add_short_term_memory({
                "role": "user",
                "content": f"任务: {task}",
            })
            self.memory_manager.add_short_term_memory({
                "role": "assistant",
                "content": f"任务结果: {'完成' if final_result['success'] else '未完成'} - {reflection.get('reason', '')}",
            })

        # 审计日志：记录任务执行
        audit_logger.log_task(
            task=task,
            success=final_result["success"],
            step_count=len(steps),
            reflection=reflection,
        )

        return final_result

    def summarize_conversation(self) -> str:
        if not self.memory_manager:
            return "没有对话历史"

        memory = self.memory_manager.get_short_term_memory()
        if not memory:
            return "没有对话历史"

        messages_text = ""
        for msg in memory:
            role = msg.get("role", "")
            content = msg.get("content", "")
            messages_text += f"{role}: {content}\n"

        prompt = f"""请简要总结以下对话内容:

{messages_text}

总结要求:
- 用中文回答
- 不超过 200 字
- 涵盖主要问题和答案
"""

        return self.engine.generate(prompt, max_tokens=500)

    def clear_memory(self):
        if self.memory_manager:
            self.memory_manager.clear_short_term_memory()
            logger.info("Memory cleared")