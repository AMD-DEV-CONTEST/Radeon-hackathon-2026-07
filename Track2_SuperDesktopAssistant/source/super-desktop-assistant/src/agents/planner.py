"""
🧠 规划 Agent —— 意图分析 → 任务分解 → 生成 JSON DAG。
"""
import json
import re
import asyncio
from loguru import logger
from ..api.llm import chat_json


def _clean_json(text: str) -> str:
    """从 LLM 输出中提取纯净 JSON。

    处理常见问题：
    - ```json ... ``` 代码块包裹
    - ``` ... ``` 代码块包裹
    - 前后的空白和解释文字
    - 控制字符
    """
    text = text.strip()
    # 尝试提取 ```json ... ``` 或 ``` ... ``` 代码块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # 移除非法控制字符（保留 \n \t）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


PLANNER_SYSTEM_PROMPT = """你是一个智能任务规划器。用户用自然语言描述需求，你将其分解为 DAG 任务图。

## 可用的节点类型

| type | 用途 |
|------|------|
| llm | 写代码、写HTML、写JSON、翻译、问答等。**LLM节点可以用工具读写文件** |
| image_gen | 生成图片（含文生图、图片编辑） |
| vision | 看图片内容 |
| stt | 语音转文字 |
| tts | 文字转语音 |

> 注意：image_edit 已被合并到 image_gen，所有图片相关任务统一使用 image_gen 节点。

## DAG 构建规则

1. 每个节点有唯一 id
2. depends_on 列出前置节点
3. prompt 要精确可执行——具体说明做什么、怎么做，不必写输出路径（Allocator 会通过公共记忆管理路径）
4. 独立任务并行，有依赖串行
5. 中间产物（大纲/脚本）用 JSON 文件保存，传路径给下游

### image_gen 节点规则

image_gen 的 prompt 必须是**NoobAI 标签格式**的视觉描述（逗号分隔的英文标签，不是自然语言）。
多张图时用 LLM 节点先生成每张图的 prompt（JSON），再各用一个 image_gen 节点。

**星野(Hoshino) 标准外貌标签**（基于 Danbooru）：
very long pink hair, huge ahoge, heterochromia, blue eyes, yellow eyes,
black plaid skirt, white collared shirt, chest harness, blue necktie, beretta 1301

> 注意：这些外貌标签必须出现在每一个包含星野的 image_gen prompt 中

## 输出格式

必须严格按照以下 JSON 结构输出，不要额外文字：

```json
{
  "task_id": "task_xxx",
  "description": "一句话描述任务",
  "nodes": [
    {
      "id": "唯一标识",
      "type": "节点类型",
      "prompt": "给执行Agent的详细指令（image_gen必须用视觉描述，不能用执行指令）",
      "depends_on": ["依赖的节点id"],
      "context_vars": {}
    }
  ],
  "user_inputs": {
    "images": "需要用户上传图片吗？(never/optional/required)",
    "audio": "需要用户上传音频吗？(never/optional/required)"
  }
}
```

现在，根据用户的需求生成 DAG。只输出 JSON，不要任何解释。"""


async def plan(
    user_message: str,
    has_image: bool = False,
    has_audio: bool = False,
    has_video: bool = False,
    conversation_history: list[dict] | None = None,
) -> str:
    context_note = ""
    if has_image:
        context_note += "\n（用户已上传图片，如果任务需要分析图片，使用 vision 节点。）"
    if has_audio:
        context_note += "\n（用户已上传音频，如果任务需要转写，使用 stt 节点。）"
    if has_video:
        context_note += "\n（用户已上传视频，如果任务需要分析视频，使用 vision 节点。）"

    messages = [{"role": "system", "content": PLANNER_SYSTEM_PROMPT}]

    # 注入最近的对话历史（最多 10 条），帮助理解上下文
    if conversation_history:
        recent = conversation_history[-10:]
        for h in recent:
            role = h.get("role", "user")
            content = h.get("content", "")[:500]
            # B3 修复：只放行 user/assistant 角色，跳过 tool/system 残留
            # （无 tool_call_id 的 tool 消息会被严格的 OpenAI 兼容 API 拒绝）
            if role not in ("user", "assistant"):
                continue
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": f"用户需求：{user_message}{context_note}"})

    logger.info(f"[PLAN] {user_message[:100]}... (历史 {len(conversation_history or [])} 条)")
    json_str = await asyncio.to_thread(chat_json, messages, capability="llm")
    # 清理 markdown 包裹和非法字符
    json_str = _clean_json(json_str)
    logger.info(f"[TRACE-PLAN] DAG JSON ({len(json_str)} chars): {json_str[:500]}...")
    return json_str


def _extract_json_object(text: str) -> str:
    """从文本中提取完整的 JSON 对象（支持任意嵌套层级）。

    使用括号计数而非正则，正确处理深层嵌套。
    """
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == "\\" and in_string:
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text  # 未找到闭合括号，返回原文让调用者报错


def _valid_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def _repair_json(text: str) -> str:
    """尝试多种策略**顺序叠加**修复损坏的 JSON。

    B1 修复：原实现各策略独立作用于原文，多重缺陷（如 代码块包裹 + 尾逗号）
    的 JSON 永远修不好。现在逐步叠加——每步对"上一步结果"继续修复并校验，
    任意一步通过即返回；全部失败回退原文。
    """
    strategies = [
        # 1. 清理控制字符 + markdown 包裹
        lambda t: _clean_json(t),
        # 2. 移除尾部逗号（常见 LLM 输出错误）
        lambda t: re.sub(r",\s*([}\]])", r"\1", t),
        # 3. 深度平衡括号提取（处理任意嵌套层级的 JSON 对象）
        lambda t: _extract_json_object(t),
        # 4. 修复未转义的实际换行符（保留已转义的 \\n）
        lambda t: re.sub(r'(?<!\\)\n', r'\\n', t),
    ]
    repaired = text
    for strategy in strategies:
        if _valid_json(repaired):
            break
        try:
            candidate = strategy(repaired)
            if candidate and candidate.strip():
                repaired = candidate
        except Exception:
            continue
    return repaired if _valid_json(repaired) else text  # 全部失败，返回原文让调用者报错


def parse_and_validate(json_str: str) -> dict:
    """解析规划输出并做完整校验。"""
    # 1. 多策略修复并解析 JSON
    repaired = _repair_json(json_str)
    try:
        data = json.loads(repaired)
    except json.JSONDecodeError as e:
        return {"error": f"规划 Agent 输出的 JSON 不合法（已尝试多种修复策略）: {e}"}

    # 2. 基本结构
    if "nodes" not in data:
        return {"error": "缺少 nodes 字段"}
    nodes = data["nodes"]
    if not isinstance(nodes, list) or len(nodes) == 0:
        return {"error": "nodes 为空"}

    # 3. 节点字段校验
    valid_types = {"llm", "vision", "stt", "tts", "image_gen", "image_edit"}  # image_edit 已弃用但向后兼容
    node_ids = set()
    for node in nodes:
        if "id" not in node:
            return {"error": "节点缺少 id"}
        nid = node["id"]
        if nid in node_ids:
            return {"error": f"节点 ID 重复: {nid}"}
        node_ids.add(nid)

        ntype = node.get("type")
        if ntype not in valid_types:
            return {"error": f"节点 {nid} 类型无效: {ntype} (有效: {valid_types})"}
        if ntype == "image_edit":
            # B5 修复：image_edit 已合并到 image_gen，自动改写，
            # 避免路由到 IMAGE_EDIT 后生图工头误当纯文生图处理（无法编辑）。
            logger.warning(f"[PLAN] 节点 {nid} 使用了已弃用的 image_edit，已自动转为 image_gen")
            node["type"] = "image_gen"

    # 4. 依赖校验
    for node in nodes:
        nid = node["id"]
        for dep in node.get("depends_on", []):
            if dep not in node_ids:
                return {"error": f"节点 {nid} 依赖了不存在的节点: {dep}"}
            if dep == nid:
                return {"error": f"节点 {nid} 依赖了自身（不允许自循环）"}

    # 5. 循环依赖检测 (DFS)
    cycle_error = _detect_cycle(nodes, node_ids)
    if cycle_error:
        return {"error": cycle_error}

    return data


def _detect_cycle(nodes: list[dict], all_ids: set[str]) -> str | None:
    """DFS 检测循环依赖。返回错误描述，无循环返回 None。"""
    dep_map = {n["id"]: n.get("depends_on", []) for n in nodes}

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in all_ids}

    def dfs(nid: str, path: list[str]) -> str | None:
        color[nid] = GRAY
        path.append(nid)
        for dep in dep_map.get(nid, []):
            if color.get(dep) == GRAY:
                cycle = " → ".join(path[path.index(dep):] + [dep])
                return f"检测到循环依赖: {cycle}"
            if color.get(dep) == WHITE:
                err = dfs(dep, path)
                if err:
                    return err
        path.pop()
        color[nid] = BLACK
        return None

    for nid in all_ids:
        if color[nid] == WHITE:
            err = dfs(nid, [])
            if err:
                return err
    return None
