"""review.py — two-phase (learn + recall) Feynman review state machine.

每张卡片两阶段：
  学习阶段: 先展示卡片核心内容，让用户读懂
  复述阶段: AI 反问"用自己的话讲一遍"，用户复述后 AI 结构化判断

结构化约束（防开放聊天漂移）：
- system prompt 锁定当前卡片，声明不是自由聊天
- 用户复述后最多 2 次澄清追问，然后必须输出结构化判断
- AI 判断：natural-language 反馈 + JSON(mastery_level 0-5, needs_retry)
- 同卡最多重讲 2 次，超限强制推进（记录中间掌握度，缩短复习间隔）
- user_override 逃生口：用户可手动确认掌握，记录标记

显式状态机 state_json：
  {"card_index": int, "phase": "learn|recall|retry|done",
   "retries": int, "judged": {card_id: judgment}}
"""
from __future__ import annotations

import json

from . import db, llm

MAX_RETRY = 2  # 同一张卡片最多允许的重讲次数


JUDGE_SYSTEM = (
    "你是费曼复述评分员。用户在尝试用自己的话复述一张学习卡片。"
    "请判断其理解程度，输出 JSON："
    '{"feedback": "给用户的自然语言反馈（肯定优点+指出不足，简短）", '
    '"mastery_level": 0-5 的整数, '
    '"needs_retry": true/false（理解明显不到位需重讲时 true）}'
    "评分标准：5=准确完整；3-4=基本正确有小错；1-2=明显偏差；0=完全不对。"
    "只针对当前卡片内容判断，不展开无关话题。"
)


def _default_state(n_cards: int) -> dict:
    return {
        "card_index": 0,
        "phase": "learn",
        "retries": 0,
        "judged": {},
        "n_cards": n_cards,
    }


def _judge(card: dict, recall_text: str) -> dict:
    """调用对话层模型做结构化判断，含容错。"""
    user = (
        f"卡片内容：{card['content']}\n"
        f"用户复述：{recall_text}\n"
        "请给出结构化判断。"
    )
    result = llm.dialogue_chat(JUDGE_SYSTEM, user, max_tokens=400, json_mode=True)
    if not result["ok"]:
        return {"ok": False, "error": result["error"]}
    try:
        j = json.loads(result["content"])
        return {
            "ok": True,
            "mastery_level": max(0, min(5, int(j.get("mastery_level", 0)))),
            "needs_retry": bool(j.get("needs_retry", False)),
            "feedback": str(j.get("feedback", "")),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"ok": False, "error": "judgment JSON parse failed", "raw": result["content"][:300]}


def start(skill_id: int) -> dict:
    """创建或续接该技能的活跃复习会话。同一技能同一时间仅一个活跃会话。"""
    skill = db.get_skill(skill_id)
    if skill is None:
        return {"ok": False, "error": "skill not found"}

    existing = db.active_session_for_skill(skill_id)
    if existing is not None:
        return {"ok": True, "resumed": True, "session": _serialize(existing)}

    cards = db.list_cards(skill_id)
    if not cards:
        return {"ok": False, "error": "该技能还没有卡片，请先上传资料抽取"}
    card_ids = [c["id"] for c in cards]
    sid = db.create_session(skill_id, card_ids)
    db.set_session_state(sid, _default_state(len(card_ids)))
    session = db.get_session(sid)
    # 自动进入第一张卡的学习阶段
    first = db.get_card(card_ids[0])
    db.append_transcript(sid, {
        "role": "ai", "stage": "learn", "card_id": card_ids[0],
        "content": f"📖 学习卡片 {1}/{len(card_ids)}：\n\n{first['content']}"
                   + (f"\n\n来源：{first['source_material']}" if first["source_material"] else ""),
    })
    db.append_transcript(sid, {
        "role": "ai", "stage": "recall", "card_id": card_ids[0],
        "content": "现在请用自己的话复述这张卡片的内容（费曼技巧）。",
    })
    state = _default_state(len(card_ids))
    state["phase"] = "recall"  # start() 已展示学习+复述提示，下一步用户输入就是复述
    db.set_session_state(sid, state)
    return {"ok": True, "resumed": False, "session": _serialize(db.get_session(sid))}


def respond(session_id: int, message: str) -> dict:
    """状态机推进：根据当前 phase 处理用户输入。"""
    session = db.get_session(session_id)
    if session is None:
        return {"ok": False, "error": "session not found"}
    if session["status"] != "进行中":
        return {"ok": False, "error": f"会话已{session['status']}"}

    state = session["state_json"]
    cards = [db.get_card(cid) for cid in session["card_ids"]]
    cards = [c for c in cards if c]

    idx = state.get("card_index", 0)
    if idx >= len(cards):
        state["phase"] = "done"
        db.set_session_state(session_id, state)
        return {"ok": True, "done": True,
                "content": "🎉 本组卡片复习完成！点击『完成会话』记录生长值，或继续上传更多资料。"}

    card = cards[idx]
    phase = state.get("phase", "learn")

    # 保存用户消息（实时落库）
    db.append_transcript(session_id, {"role": "user", "card_id": card["id"], "content": message})

    # 学习阶段：用户说"继续/开始复述" → 进入复述阶段
    if phase == "learn":
        db.append_transcript(session_id, {
            "role": "ai", "stage": "recall", "card_id": card["id"],
            "content": "请用自己的话复述这张卡片的核心内容。",
        })
        state["phase"] = "recall"
        db.set_session_state(session_id, state)
        return {"ok": True, "content": "请用自己的话复述这张卡片的核心内容。"}

    # 复述/重讲阶段：用户给了复述 → AI 判断
    if phase in ("recall", "retry"):
        judgment = _judge(card, message)
        if not judgment["ok"]:
            db.append_transcript(session_id, {
                "role": "ai", "stage": "judge_error", "card_id": card["id"],
                "content": "评分暂时不可用，请稍后再试。",
            })
            return {"ok": False, "error": judgment["error"]}

        retries = state.get("retries", 0)
        mastery = judgment["mastery_level"]
        needs_retry = judgment["needs_retry"]
        feedback = judgment["feedback"]

        if not needs_retry or mastery >= 4:
            # 通过 → 记录判断，进入下一张卡
            state["judged"][str(card["id"])] = {
                "mastery_level": mastery, "needs_retry": False, "retries": retries,
            }
            db.append_transcript(session_id, {
                "role": "ai", "stage": "judge", "card_id": card["id"],
                "content": f"✅ 判断：掌握度 {mastery}/5\n{feedback}",
                "judgment": {"mastery_level": mastery, "needs_retry": False},
            })
            _advance(session_id, state, cards, mastery)
            return {"ok": True, "judgment": {"mastery_level": mastery, "needs_retry": False},
                    "content": f"✅ 掌握度 {mastery}/5。{feedback}"}

        # 未通过
        if retries < MAX_RETRY:
            state["retries"] = retries + 1
            state["phase"] = "retry"
            db.append_transcript(session_id, {
                "role": "ai", "stage": "judge", "card_id": card["id"],
                "content": f"⚠️ 判断：掌握度 {mastery}/5。{feedback}（第 {state['retries']}/{MAX_RETRY} 次重讲）",
                "judgment": {"mastery_level": mastery, "needs_retry": True},
            })
            db.set_session_state(session_id, state)
            return {"ok": True,
                    "judgment": {"mastery_level": mastery, "needs_retry": True},
                    "content": f"⚠️ 掌握度 {mastery}/5。{feedback}\n再试一次？也可以点『跳过重讲』。"
                               f"（第 {state['retries']}/{MAX_RETRY} 次）"}

        # 超过重讲上限 → 强制推进，记录中间掌握度（下次复习间隔缩短）
        state["judged"][str(card["id"])] = {
            "mastery_level": mastery, "needs_retry": True, "retries": retries,
        }
        db.append_transcript(session_id, {
            "role": "ai", "stage": "judge", "card_id": card["id"],
            "content": f"🔁 已达重讲上限。记录中间掌握度 {mastery}/5，稍后安排更短的复习间隔。",
            "judgment": {"mastery_level": mastery, "needs_retry": True},
        })
        _advance(session_id, state, cards, mastery)
        return {"ok": True,
                "judgment": {"mastery_level": mastery, "needs_retry": True},
                "content": f"🔁 已达重讲上限，记录中间掌握度 {mastery}/5。{feedback}"}

    return {"ok": False, "error": f"unexpected phase: {phase}"}


def override_current(session_id: int) -> dict:
    """用户手动确认掌握当前卡片（逃生口），记录 user_override 标记。"""
    session = db.get_session(session_id)
    if session is None:
        return {"ok": False, "error": "session not found"}
    state = session["state_json"]
    cards = [db.get_card(cid) for cid in session["card_ids"]]
    cards = [c for c in cards if c]
    idx = state.get("card_index", 0)
    if idx >= len(cards):
        return {"ok": True, "done": True}
    card = cards[idx]
    state["judged"][str(card["id"])] = {"mastery_level": 4, "needs_retry": False, "retries": 0,
                                        "user_override": True}
    db.append_transcript(session_id, {
        "role": "ai", "stage": "override", "card_id": card["id"],
        "content": "✅ 已由用户确认掌握（user_override）。",
    })
    conn = db.get_conn()
    conn.execute("UPDATE review_sessions SET user_override=1 WHERE id=?", (session_id,))
    conn.commit()
    conn.close()
    _advance(session_id, state, cards, 4)
    return {"ok": True, "content": "已标记掌握，进入下一张。"}


def _advance(session_id: int, state: dict, cards: list, last_mastery: int) -> None:
    """推进到下一张卡（学习阶段），全部完成则置 done。"""
    idx = state.get("card_index", 0) + 1
    state["card_index"] = idx
    state["phase"] = "learn"
    state["retries"] = 0

    if idx >= len(cards):
        state["phase"] = "done"
        db.set_session_state(session_id, state)
        return

    card = cards[idx]
    db.append_transcript(session_id, {
        "role": "ai", "stage": "learn", "card_id": card["id"],
        "content": f"📖 学习卡片 {idx + 1}/{len(cards)}：\n\n{card['content']}"
                   + (f"\n\n来源：{card['source_material']}" if card["source_material"] else ""),
    })
    db.set_session_state(session_id, state)


def _serialize(session: dict) -> dict:
    """返回给前端的精简会话结构（含最新状态）。"""
    cards = [db.get_card(cid) for cid in session["card_ids"]]
    cards = [c for c in cards if c]
    state = session["state_json"]
    idx = state.get("card_index", 0)
    return {
        "id": session["id"],
        "skill_id": session["skill_id"],
        "status": session["status"],
        "card_index": idx,
        "total_cards": len(cards),
        "phase": state.get("phase", "learn"),
        "retries": state.get("retries", 0),
        "judged": state.get("judged", {}),
        "user_override": bool(session["user_override"]),
        "transcript": session["transcript"],
        "created_at": session["created_at"],
        "completed_at": session["completed_at"],
    }
