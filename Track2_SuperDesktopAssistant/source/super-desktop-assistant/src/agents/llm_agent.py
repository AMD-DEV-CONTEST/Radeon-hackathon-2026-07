"""
💬 LLM 执行 Agent —— 处理纯文本推理任务。

v3: 对接 SharedMemory（公共记忆）架构。
- 通过 get_shared_memory 工具获取 Allocator 分配的上下文
- 可以 add_note / add_discovery 向公共记忆追加发现
"""
import asyncio
from functools import partial
from ..orchestration.executor import register_agent
from ..orchestration.dag import NodeType
from ..api.llm import chat, chat_with_tools
from .tools import AGENT_TOOLS, execute_tool
from loguru import logger


@register_agent(NodeType.LLM)
async def execute_llm(node, prompt: str, context: dict) -> str:
    logger.info(f"[LLM] [{node.id}] {prompt[:80]}...")

    messages = [
        {"role": "system", "content": (
            "你是一个 AI 助手，工作在一个多 Agent 协作系统中。\n\n"
            "你有以下工具：\n"
            "- get_shared_memory(agent_id): 获取任务上下文、其他Agent状态、**输出目录路径**\n"
            "- read_file(path): 读取文件内容\n"
            "- write_file(path, content): 写入文件(HTML/JSON等)\n"
            "- search_code(path, pattern): 搜索代码\n"
            "- list_files(path): 列出目录\n"
            "- generate_image(prompt, size, cfg, steps, prefix): 生成动漫图片\n"
            "- add_note(content, prefix): 分享笔记给其他Agent\n"
            "- add_discovery(content): 追加发现\n\n"
            "重要：\n"
            "1. 首先调用 get_shared_memory 获取任务上下文，其中包含 Allocator 分配的输出路径\n"
            "2. 最终产出应是实际文件（HTML、py、JSON 等），用 write_file 保存\n"
            "3. 工具调用完成后，最后一步必须用 write_file 保存成品\n"
            "4. 生图 prompt 必须用 NoobAI 标签格式（逗号分隔英文标签），前面加 very awa, masterpiece, best quality, newest, highres, absurdres。\n"
            "5. 星野(Hoshino)的标准外貌标签（来自 Danbooru，10k+ 图片）：very long pink hair, huge ahoge, heterochromia, blue eyes, yellow eyes, black plaid skirt, white collared shirt, chest harness, blue necktie, beretta 1301。生成星野的图片时必须包含这些标签！不要自己编（浅蓝发/短发/橙色眼睛都是错的）"
        )},
    ]

    # 注入对话历史（B3 修复：只放行 user/assistant，跳过 tool/system 残留）
    conv_history = context.get("_conversation_history", [])
    if conv_history:
        for h in conv_history[-6:]:
            role = h.get("role", "user")
            content = h.get("content", "")[:1000]
            if role not in ("user", "assistant"):
                continue
            messages.append({"role": role, "content": content})

    # 注入前序节点上下文
    context_parts = []
    for dep_id in node.depends_on:
        dep_result = context.get(dep_id)
        if dep_result is not None:
            context_parts.append(f"【{dep_id} 的结果】\n{dep_result}")

    if context_parts:
        prompt = "\n\n".join(context_parts) + f"\n\n---\n用户指令：{prompt}"

    messages.append({"role": "user", "content": prompt})

    # 工具回调：绑定 agent_id
    def tool_handler(tool_name: str, args: dict) -> str:
        return execute_tool(tool_name, args, agent_id=node.id)

    from ..config import get_config
    s = get_config().settings
    try:
        result = await asyncio.to_thread(
            chat_with_tools,
            messages=messages,
            tools=AGENT_TOOLS,
            on_tool_call=tool_handler,
            temperature=s.llm_agent_temperature,
            max_tokens=s.llm_agent_max_tokens,
            max_tool_rounds=s.max_tool_rounds,
        )
    except Exception as e:
        # 永久错误（鉴权/配额/模型不存在）直接抛出，不降级
        from ..api.errors import is_permanent_error
        if is_permanent_error(str(e)):
            raise
        err_msg = str(e).lower()
        # C2 修复：去掉宽泛的 "invalid"（"invalid temperature" 等会被误判为不支持工具）。
        # 只对明确的"不支持工具/函数/参数"类错误降级。
        if any(k in err_msg for k in ("tool", "function", "not support",
                                      "unknown parameter", "unrecognized")):
            logger.info(f"[LLM] [{node.id}] 工具调用不支持，降级为普通对话")
            try:
                result = await asyncio.to_thread(chat, messages)
            except Exception:
                raise  # 降级也失败，传播原始错误
        else:
            raise

    logger.debug(f"[LLM] [{node.id}] -> {len(result)} chars")
    return result
