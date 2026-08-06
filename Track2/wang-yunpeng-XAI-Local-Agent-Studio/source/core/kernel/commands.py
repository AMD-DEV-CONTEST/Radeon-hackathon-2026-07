"""V4 内核：斜杠命令处理器（Task #193 Phase B）。

从 engine_xai.py 上帝类外移全部 _cmd_* 命令处理器。命令逻辑不变，
仅将 self 改为 engine 参数（engine 引用总线/适配器/记忆/控制环等）。
"""

import time
from typing import Any, Dict, Generator, List

from .base import SLASH_COMMANDS, Intent

def cmd_help(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    if args:
        cmd = SLASH_COMMANDS.get(args.strip().lower())
        if cmd:
            yield {"type": "answer", "answer": f"/{cmd.name}: {cmd.description}\n用法: {cmd.usage}"}
        else:
            yield {"type": "answer", "answer": f"未知命令: {args}\n输入 /help 查看所有命令"}
    else:
        lines = ["可用命令:"]
        for name, cmd in SLASH_COMMANDS.items():
            lines.append(f"  /{name}  {cmd.description}")
        yield {"type": "answer", "answer": "\n".join(lines)}



def cmd_skill(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    parts = args.split(maxsplit=2)
    action = parts[0].lower() if parts else "list"
    name = parts[1] if len(parts) > 1 else ""
    desc = parts[2] if len(parts) > 2 else ""

    if action == "list":
        # 优先展示 OpenClaw 真实技能，其次本地技能
        real = engine.openclaw.list_real_skills()
        if real.ok and real.meta.get("count", 0) > 0:
            yield {"type": "answer", "answer": f"OpenClaw 真实技能（{real.meta['count']} 个）:\n{real.output}"}
            return
        r = engine.hermes.list_skills()
        yield {"type": "answer", "answer": f"已注册技能:\n{r.output}"}
    elif action == "load" and name:
        r = engine.openclaw.load_real_skill(name) if engine.openclaw.is_available() else engine.hermes.load_skill(name)
        yield {"type": "answer", "answer": r.output if r.ok else f"❌ {r.error}"}
    elif action == "register" and name:
        r = engine.hermes.register_skill(name, desc, "")
        yield {"type": "answer", "answer": r.output if r.ok else f"❌ {r.error}"}
    else:
        yield {"type": "answer", "answer": "用法: /skill [list|load|register] <名称> [描述]"}



def cmd_mcp(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    parts = args.split(maxsplit=1)
    action = parts[0].lower() if parts else "list"
    name = parts[1] if len(parts) > 1 else ""

    if action == "list":
        r = engine.openclaw.mcp_list_servers()
        yield {"type": "answer", "answer": f"MCP 服务器:\n{r.output}"}
    elif action == "add" and name:
        r = engine.openclaw.mcp_add(name)
        yield {"type": "answer", "answer": r.output if r.ok else f"❌ {r.error}"}
    elif action == "connect" and name:
        # 兼容旧用法：connect 等价于 add
        r = engine.openclaw.mcp_add(name)
        yield {"type": "answer", "answer": r.output if r.ok else f"❌ {r.error}"}
    elif action == "tools":
        r = engine.openclaw.mcp_list_tools(name)
        yield {"type": "answer", "answer": f"MCP 工具:\n{r.output}" if r.ok else f"❌ {r.error}"}
    else:
        yield {"type": "answer", "answer": "用法: /mcp [list|add|tools] <服务器名>"}



def cmd_task(engine, args: str, session_id: str) -> Generator[Dict[str, Any], None, None]:
    """任务：直接规划并执行（不再只是「创建」）。"""
    if not args:
        yield {"type": "answer", "answer": "用法: /task <任务描述>\n系统会自动拆解并执行该任务。"}
        return

    yield {"type": "progress", "stage": "task_plan", "text": f"正在规划任务: {args[:100]}"}
    history = engine._sessions.get_history(session_id, limit=24)
    # 复用通用推理执行（带流式 + 多轮）
    yield from engine._execute_general(f"请作为任务执行引擎，完成任务：{args}", history)



def cmd_automate(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    if not args:
        r = engine.openclaw.list_cron()
        yield {"type": "answer", "answer": f"定时任务:\n{r.output}"}
        return

    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        yield {"type": "answer", "answer": "用法: /automate <cron表达式> <命令>\n示例: /automate '0 8 * * *' 'python report.py'"}
        return

    schedule = parts[0]
    command = parts[1]
    r = engine.openclaw.schedule_cron("auto", schedule, command)
    yield {"type": "answer", "answer": r.output if r.ok else f"❌ {r.error}"}



def cmd_remember(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    if not args:
        yield {"type": "answer", "answer": "用法: /remember <要记住的内容>"}
        return
    try:
        # V4: 直接写入 memory_core（删除 MemoryAdapter 双轨）
        pid = None
        try:
            p = engine.project_manager.current()
            pid = p.id if p else None
        except Exception:
            pass
        engine.memory_core.store(
            layer="long_term",
            key=f"remember:{int(time.time())}",
            value=args[:2000],
            engine="xai",
            importance=0.8,
            meta={"intent": "remember", "source": "slash_command", "project_id": pid},
        )
        yield {"type": "answer", "answer": f"✅ 已记住: {args[:200]}"}
    except Exception as e:
        yield {"type": "answer", "answer": f"❌ 记忆写入失败: {e}"}



def cmd_recall(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    yield from engine._execute_memory_query(args or "")

# ---- 审批队列 ----



def cmd_approve(engine, args: str, session_id: str = "") -> Generator[Dict[str, Any], None, None]:
    aid = args.strip()
    rec = engine._pending_approvals.get(aid)
    if not rec:
        yield {"type": "answer", "answer": f"审批 ID 不存在: {aid}"}
        return
    if rec["status"] != "pending":
        yield {"type": "answer", "answer": f"{aid} 已处理（{rec['status']}）"}
        return
    rec["status"] = "approved"
    yield {"type": "answer", "answer": f"✅ 已批准 {aid}，正在执行原操作..."}
    # 批准后真正执行原意图
    sid = session_id or rec.get("session", "default")
    intent = Intent(rec.get("intent") or "general", 0.8, "审批后执行")
    history = engine._sessions.get_history(sid, limit=24)
    try:
        for ev in engine._execute_intent(intent, rec["detail"], sid, history):
            yield ev
    except Exception as e:
        yield {"type": "error", "error": f"执行原操作失败: {e}"}



def cmd_reject(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    aid = args.strip()
    rec = engine._pending_approvals.get(aid)
    if not rec:
        yield {"type": "answer", "answer": f"审批 ID 不存在: {aid}"}
        return
    rec["status"] = "rejected"
    yield {"type": "answer", "answer": f"❌ 已拒绝 {aid}"}



def cmd_loop(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    """认知控制环：reason → meta → guardian → execute 单向管线。"""
    task = args.strip()
    if not task:
        yield {"type": "answer", "answer": "用法: /loop <任务描述>"}
        return
    yield {"type": "progress", "stage": "loop", "text": f"启动认知控制环: {task[:60]}"}
    try:
        result = engine.control_loop.act(task)
        yield {"type": "answer", "answer": f"🧠 [控制环完成 · 校准置信度 {result.calibrated_confidence:.2f}]\n\n{result.answer[:2000]}"}
    except Exception as e:
        yield {"type": "error", "error": f"控制环异常: {e}"}



def cmd_plan(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    """V4 Planner: 目标 → 步骤 → Agent 分配。"""
    goal = args.strip()
    if not goal:
        yield {"type": "answer", "answer": "用法: /plan <任务目标>"}
        return
    plan = engine.planner.plan(goal)
    yield {"type": "progress", "stage": "plan", "text": f"规划完成: {len(plan.steps)} 个步骤"}
    lines = [f"## {plan.goal}", f"*{plan.rationale}*", ""]
    for s in plan.steps:
        deps = f" ← 依赖 step {s.depends_on}" if s.depends_on else ""
        lines.append(f"{s.step_id}. [{s.agent}] {s.task}{deps}")
    yield {"type": "answer", "answer": "\n".join(lines)}



def cmd_scan(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    """安全漏洞扫描"""
    filepath = args.strip() or "generated.py"
    r = engine.openclaw.vulnerability_scan({"file": filepath})
    if not r.ok:
        yield {"type": "error", "error": r.error or "扫描失败"}
        return
    yield {"type": "answer", "answer": r.output}



def cmd_evolve(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    """Darwinian 技能进化（用 LLM 生成有意义的变异）"""
    skill_name = args.strip()
    yield {"type": "progress", "stage": "evolve", "text": f"正在执行 Darwinian 进化{' (' + skill_name + ')' if skill_name else ''}..."}
    r = engine.hermes.darwinian_evolve(skill_name)
    yield {"type": "answer", "answer": r.output if r.ok else f"❌ {r.error}"}
    r2 = engine.hermes.list_pending_reviews()
    if r2.ok and r2.meta.get("count", 0) > 0:
        yield {"type": "answer", "answer": f"待复审:\n{r2.output}"}



def cmd_models(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    """列出可用 AI 模型"""
    r = engine.hermes.list_models()
    yield {"type": "answer", "answer": f"可用模型:\n{r.output}"}



def cmd_channels(engine, args: str) -> Generator[Dict[str, Any], None, None]:
    """消息渠道管理"""
    parts = args.split(maxsplit=1)
    action = parts[0].lower() if parts else "list"
    if action == "status" and len(parts) > 1:
        r = engine.openclaw.channel_status(parts[1])
        yield {"type": "answer", "answer": r.output if r.ok else f"❌ {r.error}"}
    else:
        r = engine.openclaw.list_channels()
        yield {"type": "answer", "answer": f"支持的消息渠道:\n{r.output}"}



def cmd_diagnose(engine) -> Generator[Dict[str, Any], None, None]:
    """系统全面自检"""
    yield {"type": "progress", "stage": "diagnose", "text": "正在全系统自检..."}
    import datetime
    lines = ["# XAI 系统体检报告", f"时间: {datetime.datetime.now().isoformat()}", ""]

    s = engine.status()
    lines += ["## 1. 引擎状态", f"- XAI 引擎: {s['xai_engine']}", f"- 模型后端: {s['model']}",
              f"- 斜杠命令: {s['slash_commands']} 个", f"- 待审批: {s['pending_approvals']}", ""]

    oc_health = engine.openclaw.health_check()
    lines += ["## 2. 执行底座 — OpenClaw", f"- 状态: {'✅ 正常' if oc_health.ok else '❌ 异常'}",
              f"- 模式: {oc_health.meta.get('mode', 'unknown')}", f"- 信息: {oc_health.output[:100]}"]
    mcp_r = engine.openclaw.mcp_list_servers()
    lines.append(f"- MCP: {mcp_r.output[:100]}")
    skill_r = engine.openclaw.list_real_skills()
    if skill_r.ok:
        lines.append(f"- 真实技能: {skill_r.meta.get('count', 0)} 个")
    ch_r = engine.openclaw.list_channels()
    if ch_r.ok:
        lines.append(f"- 渠道: {len(ch_r.meta.get('channels', []))} 个")
    lines.append("")

    hm_health = engine.hermes.health_check()
    lines += ["## 3. AI 推理 — Hermes", f"- 状态: {'✅ 正常' if hm_health.ok else '❌ 异常'}",
              f"- 模式: {hm_health.meta.get('mode', 'unknown')}"]
    model_r = engine.hermes.list_models()
    if model_r.ok:
        lines.append(f"- 可用模型: {len(model_r.output.strip().split(chr(10)))} 个")
    real_skills = engine.hermes.list_real_skills()
    if real_skills.ok:
        lines.append(f"- Hermes 技能包: {real_skills.meta.get('total_skills', 0)} 个")
    lines.append("")

    mem_stats = engine.memory_core.stats()
    if isinstance(mem_stats, dict):
        total = sum(mem_stats.values())
        lines += ["## 4. 记忆系统", f"- 总记忆条数: {total}"]
        for layer, count in mem_stats.items():
            lines.append(f"  - {layer}: {count} 条")
        lines.append("")

    lines += ["## 5. 治理平面 — Guardian（内嵌进程，无需独立服务）", "- P0（致命）：阻断 + 二次确认",
              "- P1（高危）：记录 + 提示", "- P2（常规）：自动通过",
              "- 高危操作需 /approve 显式授权后才真正执行", ""]

    lines += ["## 6. 会话与历史", f"- 历史会话数: {len(engine._sessions.list_sessions())}", ""]

    lines += ["## 7. 桌面 App", "- XAI.app: /Users/Admin/Desktop/XAI.app",
              "- 启动方式: 双击 或 http://localhost:8000", ""]

    # mem_stats 已是 dict（来自 memory_core.stats()），无 .ok 属性
    mem_ok = isinstance(mem_stats, dict)
    ok_count = sum(1 for h in [oc_health, hm_health] if h.ok) + (1 if mem_ok else 0)
    total = 3
    health_score = ok_count / total * 100
    lines += ["## 8. 健康评分", f"- 组件健康度: {ok_count}/{total} ({health_score:.0f}%)"]
    if health_score >= 100:
        lines.append("✅ 全系统正常运行")
    elif health_score >= 66:
        lines.append("⚠️ 部分组件异常，请检查")
    else:
        lines.append("❌ 系统异常，需修复")
    lines += ["", "---", "体检完成。使用 /help 查看所有命令"]

    yield {"type": "answer", "answer": "\n".join(lines)}

# ---- 工具方法 ----

# 高危操作关键词（命中即提升为 P0/P1 待审批）已统一收敛到 guardian_bridge 模块常量，
# 此处不再重复定义，避免双事实源。

