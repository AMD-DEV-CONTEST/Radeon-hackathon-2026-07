"""Multi-agent cross-validation of candidate events.

Each selected event is independently reviewed by two reviewers with different
perspectives (blade/action technique vs footwork/timing). If they agree, the
verdict stands; if they disagree, an arbiter sees both reasonings and decides.
"""

import json
import os

from ..data.writer import write_json
from .base import create_agent, parse_verdict

EVENT_KIND_ZH = {
    "lunge": "弓步 (lunge)",
    "action_attack": "进攻 (attack)",
    "action_parry": "格挡防守 (parry)",
    "action_counter": "反击 (counter/riposte)",
    "reaction": "反应时间样本",
}

REVIEWER_ROLES = {
    "action_reviewer": (
        "动作技术审查员",
        "你是一名资深击剑技术分析师，专注于武器动作：手臂伸展、剑的姿态、进攻与防守动作的技术要领。",
    ),
    "footwork_reviewer": (
        "步法时机审查员",
        "你是一名资深击剑步法教练，专注于步法与时机：弓步的蹬地与前腿到位、前进后退的节奏、双方距离与时机把握。",
    ),
}

ARBITER_SYSTEM = "你是一名国际级击剑裁判，负责在两位分析师意见分歧时做出最终裁定。"


def _kind_zh(kind):
    return EVENT_KIND_ZH.get(kind, kind)


def _review_prompt(event, weapon):
    detail = json.dumps(event.get("detail", {}), ensure_ascii=False)
    return f"""以下是从击剑训练视频中自动检测到的一个候选事件，附有按时间顺序排列的关键帧截图（左侧红色骨架为左方剑手，右侧蓝色为右方剑手）。

事件类型: {_kind_zh(event['kind'])}
涉及剑手: {'左方' if event['fencer'] == 'left' else '右方'}
时间: {event['start_sec']:.1f}s - {event['end_sec']:.1f}s
剑种设定: {weapon}
检测系统给出的特征: {detail}

请根据关键帧判断该事件标注是否正确（事件类型与涉及剑手都要对得上画面）。

只输出一个 JSON 对象，不要输出其他内容:
{{"verdict": "confirm" 或 "reject" 或 "uncertain", "confidence": 0到1的小数, "reasoning": "简短中文理由，指出画面中的关键证据"}}"""


def _arbiter_prompt(event, weapon, verdicts):
    lines = "\n".join(
        f"- {v.reviewer}: {v.verdict} (置信度 {v.confidence:.2f}) 理由: {v.reasoning}"
        for v in verdicts
    )
    return f"""两位分析师对同一个候选事件意见分歧，请你根据关键帧做最终裁定。

事件类型: {_kind_zh(event['kind'])}，涉及剑手: {'左方' if event['fencer'] == 'left' else '右方'}，时间 {event['start_sec']:.1f}s-{event['end_sec']:.1f}s，剑种设定: {weapon}。

两位分析师的意见:
{lines}

只输出一个 JSON 对象:
{{"verdict": "confirm" 或 "reject" 或 "uncertain", "confidence": 0到1的小数, "reasoning": "简短中文理由"}}"""


def cross_validate(output_dir, events, manifest, config):
    agent = create_agent(config)
    if agent is None:
        print("No agent backend available; skipping cross-validation "
              "(run with --skip-agents to silence this, or set ANTHROPIC_API_KEY / VLM_BASE_URL).")
        return None, None

    weapon = config.get("weapon", "general")
    max_events = config["agents"]["max_events_to_review"]

    candidates = [e for e in manifest if e.get("keyframes")]
    candidates.sort(key=lambda e: -e.get("confidence", 0))
    candidates = candidates[:max_events]

    print(f"Cross-validating {len(candidates)} events with agent backend '{agent.name}'...")
    validated = []
    for event in candidates:
        keyframes = [os.path.join(output_dir, p) for p in event["keyframes"]]
        keyframes = [p for p in keyframes if os.path.exists(p)]
        if not keyframes:
            continue

        verdicts = []
        for role_key, (role_name, role_system) in REVIEWER_ROLES.items():
            prompt = f"{role_system}\n\n{_review_prompt(event, weapon)}"
            try:
                verdicts.append(agent.review(role_name, prompt, keyframes))
            except Exception as exc:
                print(f"  {event['id']}: reviewer '{role_name}' failed: {exc}")

        if not verdicts:
            continue

        opinions = {v.verdict for v in verdicts}
        if len(opinions) == 1:
            final_verdict = verdicts[0].verdict
            final_conf = sum(v.confidence for v in verdicts) / len(verdicts)
            final_reason = " / ".join(v.reasoning for v in verdicts)
            arbiter = None
        else:
            try:
                text = agent.query(f"{ARBITER_SYSTEM}\n\n{_arbiter_prompt(event, weapon, verdicts)}",
                                   image_paths=keyframes)
                arb = parse_verdict(text, reviewer=f"{agent.name}/仲裁裁判")
            except Exception as exc:
                print(f"  {event['id']}: arbiter failed: {exc}")
                arb = None
            if arb is not None:
                final_verdict, final_conf, final_reason = arb.verdict, arb.confidence, arb.reasoning
                arbiter = arb.to_dict()
            else:
                final_verdict, final_conf, final_reason = "uncertain", 0.3, "审查意见分歧且仲裁失败"
                arbiter = None

        print(f"  {event['id']} [{event['kind']}] -> {final_verdict} ({final_conf:.2f})")
        validated.append({
            "id": event["id"],
            "kind": event["kind"],
            "fencer": event["fencer"],
            "start_sec": event["start_sec"],
            "end_sec": event["end_sec"],
            "clip": event.get("clip"),
            "keyframes": event.get("keyframes"),
            "detector_confidence": event.get("confidence"),
            "verdict": final_verdict,
            "confidence": round(final_conf, 3),
            "reasoning": final_reason,
            "reviews": [v.to_dict() for v in verdicts],
            "arbiter": arbiter,
        })

    validated_path = os.path.join(output_dir, "validated_events.json")
    write_json(validated_path, {"schema_version": "1.0", "backend": agent.name, "events": validated})
    confirmed = sum(1 for v in validated if v["verdict"] == "confirm")
    print(f"Cross-validation done: {confirmed}/{len(validated)} confirmed -> {validated_path}")
    return validated_path, validated
