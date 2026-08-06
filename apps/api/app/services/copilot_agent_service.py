"""Plan client-executable Copilot agent actions (tools the browser runs)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def plan_client_actions(
    message: str,
    page: str,
    server_diag: Optional[Dict[str, Any]] = None,
    client_diag: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Rule-based action planner — complements LLM answers with clickable agent tools."""
    msg = (message or "").strip()
    lower = msg.lower()
    actions: List[Dict[str, str]] = []
    seen: set[str] = set()

    def add(action: Dict[str, str]) -> None:
        key = f"{action['type']}:{action.get('label', '')}"
        if key not in seen and len(actions) < 5:
            seen.add(key)
            actions.append(action)

    rt_ok = (server_diag or {}).get("realtime", {}).get("ok")
    la_ok = (client_diag or {}).get("localAgent", {}).get("ok")

    wants_virtual_help = any(
        k in msg for k in ("虚拟", "演示", "reachy", "没硬件", "没有机械臂", "怎么玩", "播放", "dance", "动作")
    )
    wants_handhold = any(k in msg for k in ("怎么", "不会", "教我", "引导", "新手", "帮我", "代劳", "打开"))

    if "/reachy" in page:
        if wants_handhold or wants_virtual_help:
            add({"type": "start_reachy_guide", "label": "手把手带我玩（虚拟模式全套）"})
        if wants_virtual_help or "虚拟" in msg:
            add({"type": "reachy_virtual_start", "label": "启动虚拟模式并继续引导"})
            add({"type": "reachy_play_demo", "label": "播放 hello 演示"})
        if not la_ok:
            add({"type": "navigate", "href": "/setup", "label": "打开 Setup 装 Agent"})

        # M26 — robot-driving actions. The user can drive the robot by talking
        # to the assistant instead of hunting for buttons in the control panel.
        emotion = _detect_emotion(msg)
        if emotion:
            add({"type": "reachy_play_emotion", "emotion": emotion, "label": f"播放表情：{emotion}"})
        dance = _detect_dance(msg)
        if dance:
            add({"type": "reachy_play_dance", "dance": dance, "label": f"播放舞蹈：{dance}"})
        goto_target = _detect_goto(msg)
        if goto_target:
            add({"type": "reachy_goto", **goto_target, "label": "让机器人转到目标姿态"})
        if _wants_chat(msg):
            add({"type": "reachy_start_chat", "label": "在对话栏开始聊天"})
        if _wants_head_tracker(msg):
            add({"type": "reachy_start_head_tracker", "label": "启动头部跟踪看着你"})

    elif "/robots/b601_rs" in page or "b601" in lower:
        add({"type": "b601_run_health_check", "label": "检测 B601 连接状态"})
        if any(k in msg for k in ("软", "没力", "瘫", "fault", "恢复")):
            add({"type": "b601_run_recover", "label": "恢复机械臂"})
        if any(k in msg for k in ("遥操", "teleop", "跟着动")):
            add({"type": "navigate", "href": "/robots/b601_rs", "label": "打开 B601 控制台"})
        if not la_ok:
            add({"type": "b601_install_local_agent", "label": "获取一键安装命令"})

    elif "/robots/so101" in page:
        add({"type": "navigate", "href": "/setup", "label": "打开 Setup"})
        add({"type": "start_product_tour", "label": "重新看网站引导"})

    elif "/robots" in page:
        add({"type": "start_product_tour", "label": "开始新手引导"})
        add({"type": "navigate", "href": "/robots/reachy_mini?guide=virtual", "label": "去 Reachy 虚拟演示"})
        add({"type": "navigate", "href": "/robots/b601_rs", "label": "去 B601 机械臂"})
        add({"type": "navigate", "href": "/setup", "label": "我有机械臂 · 去 Setup"})

    elif "/setup" in page:
        add({"type": "run_diagnose", "label": "重新检测 Agent"})
        add({"type": "navigate", "href": "/robots", "label": "Agent 好了 · 选机器人"})

    elif any(p in page for p in ("/datasets", "/training", "/skills", "/workflow")):
        add({"type": "navigate", "href": "/robots/so101", "label": "从 SO-101 向导开始"})
        add({"type": "start_product_tour", "label": "看网站总引导"})

    if any(k in msg for k in ("诊断", "检测", "为什么", "失败", "报错", "502", "404")):
        add({"type": "run_diagnose", "label": "运行系统诊断"})

    if wants_virtual_help and "/reachy" not in page:
        add({"type": "navigate", "href": "/robots/reachy_mini?guide=virtual", "label": "打开 Reachy 虚拟模式"})

    if any(k in msg for k in ("setup", "agent", "安装", "local agent")):
        add({"type": "navigate", "href": "/setup", "label": "打开 Setup 页面"})

    if rt_ok is False and "/reachy" not in page:
        add({"type": "run_diagnose", "label": "检查云端服务状态"})

    return actions


# ---------------------------------------------------------------------------
# M26 — Intent detection helpers for robot-driving actions.
# ---------------------------------------------------------------------------

# Canonical Reachy Mini emotion moves (subset of pollen-robotics/reachy-mini-emotions-library)
_EMOTION_KEYWORDS: Dict[str, tuple[str, ...]] = {
    "happy": ("开心", "高兴", "快乐", "happy", "smile", "笑"),
    "sad": ("难过", "伤心", "sad", "cry"),
    "excited": ("兴奋", "激动", "excited", "哇塞"),
    "calm": ("平静", "淡定", "calm", "chill"),
    "angry": ("生气", "愤怒", "angry", "mad"),
    "surprised": ("惊讶", "吃惊", "surprised", "wow"),
    "yes": ("点头", "对", "yes", "nod", "agree"),
    "no": ("摇头", "不对", "no", "deny", "disagree"),
}

# Canonical dances (subset of pollen-robotics/reachy-mini-dances-library)
_DANCE_KEYWORDS: Dict[str, tuple[str, ...]] = {
    "hello": ("你好", "打招呼", "hello", "hi", "wave"),
    "wave": ("挥手", "招手", "wave", "bye"),
    "nod": ("点头", "nod"),
    "shake": ("摇头", "shake"),
    "wiggle": ("扭一扭", "摆动", "wiggle"),
    "dance": ("跳个舞", "跳支舞", "来一段舞", "dance", "boogie"),
}


def _detect_emotion(msg: str) -> Optional[str]:
    lower = msg.lower()
    for emotion, kws in _EMOTION_KEYWORDS.items():
        for kw in kws:
            if kw in lower:
                return emotion
    return None


def _detect_dance(msg: str) -> Optional[str]:
    lower = msg.lower()
    # Prefer the explicit "dance" intent over individual move keywords.
    for dance, kws in _DANCE_KEYWORDS.items():
        for kw in kws:
            if kw in lower:
                return dance
    return None


def _detect_goto(msg: str) -> Optional[Dict[str, float]]:
    """Detect a goto intent. Returns head_pose + body_yaw payload, or None."""
    lower = msg.lower()
    if not any(k in msg for k in ("转", "看", "面向", "goto", "转向", "扭头", "抬头", "低头")):
        return None
    payload: Dict[str, float] = {
        "pitch": 0.0,
        "yaw": 0.0,
        "roll": 0.0,
        "bodyYaw": 0.0,
        "duration": 1.5,
    }
    if "左" in msg or "left" in lower:
        payload["yaw"] = 0.4
    elif "右" in msg or "right" in lower:
        payload["yaw"] = -0.4
    if "上" in msg or "抬头" in msg or "up" in lower:
        payload["pitch"] = -0.2
    elif "下" in msg or "低头" in msg or "down" in lower:
        payload["pitch"] = 0.2
    return payload


def _wants_chat(msg: str) -> bool:
    return any(k in msg for k in ("聊天", "对话", "说话", "跟你聊", "问个", "问一下", "跟我聊"))


def _wants_head_tracker(msg: str) -> bool:
    return any(k in msg for k in ("看着我", "看着我的脸", "看我", "跟踪我", "head track", "跟着我", "盯着我"))
