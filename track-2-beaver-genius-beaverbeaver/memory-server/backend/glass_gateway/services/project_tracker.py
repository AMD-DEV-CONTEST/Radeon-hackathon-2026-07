from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import threading
from typing import Any


STATUS_LABELS = {
    "completed": "已完成",
    "in_progress": "进行中",
    "at_risk": "有风险",
    "planned": "计划中",
    "blocked": "已阻塞",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def default_project_snapshot() -> dict[str, Any]:
    milestones = [
        {
            "id": "capture-evidence",
            "name": "稳定采集与原始证据",
            "phase": "phase-1",
            "owner": "眼镜端 / Bridge",
            "status": "completed",
            "progress": 100,
            "target_date": "2026-07-10",
            "summary": "拔线采集、连续音频、五秒视觉证据与时间对齐已形成工程闭环。",
            "priority": "high",
        },
        {
            "id": "asr-presence",
            "name": "语音存在判断与可核对 ASR",
            "phase": "phase-1",
            "owner": "AI Pipeline",
            "status": "at_risk",
            "progress": 55,
            "target_date": "2026-08-07",
            "summary": "工程链路可用，公开集门槛与真实眼镜验收仍需补齐。",
            "priority": "high",
        },
        {
            "id": "first-person-caption",
            "name": "第一人称经历理解",
            "phase": "phase-1",
            "owner": "Multimodal",
            "status": "in_progress",
            "progress": 65,
            "target_date": "2026-08-14",
            "summary": "caption-only 生产代码与工程 Gate 完成，语义质量与 Device Gate 待验证。",
            "priority": "high",
        },
        {
            "id": "everos-memory",
            "name": "连续上下文与 EverOS 长期记忆",
            "phase": "phase-1",
            "owner": "Memory Platform",
            "status": "in_progress",
            "progress": 72,
            "target_date": "2026-08-21",
            "summary": "持久化已验证，caption-only 迁移和跨窗口质量仍在收口。",
            "priority": "high",
        },
        {
            "id": "web-workbench",
            "name": "Web 记忆工作台与证据查看",
            "phase": "phase-1",
            "owner": "Web",
            "status": "in_progress",
            "progress": 85,
            "target_date": "2026-08-07",
            "summary": "记忆总览、Capsule 与证据页面已实现，真机新片段可见时延待补验。",
            "priority": "medium",
        },
        {
            "id": "memory-search",
            "name": "多模态记忆搜索",
            "phase": "phase-1",
            "owner": "Retrieval / Web",
            "status": "at_risk",
            "progress": 68,
            "target_date": "2026-08-28",
            "summary": "工程闭环具备；双链路迁移、语义质量与真机 Gate 仍为发布前条件。",
            "priority": "high",
        },
        {
            "id": "object-last-seen",
            "name": "物品最后看到",
            "phase": "phase-1",
            "owner": "Object Memory",
            "status": "at_risk",
            "progress": 60,
            "target_date": "2026-08-28",
            "summary": "Engineering Demo Gate 通过，位置、身份和记忆价值的语义正确性待验证。",
            "priority": "high",
        },
        {
            "id": "stability",
            "name": "四小时稳定运行与弱网恢复",
            "phase": "phase-1",
            "owner": "Platform / Device",
            "status": "planned",
            "progress": 25,
            "target_date": "2026-09-04",
            "summary": "需要完成连续下午、插拔、弱网、幂等与故障恢复验收。",
            "priority": "high",
        },
        {
            "id": "people-identity",
            "name": "人物与说话人候选",
            "phase": "phase-2",
            "owner": "Identity",
            "status": "planned",
            "progress": 12,
            "target_date": "2026-09-25",
            "summary": "人脸、声纹候选、用户确认与长期人物档案。",
            "priority": "medium",
        },
        {
            "id": "meeting-actions",
            "name": "会议、承诺与待办",
            "phase": "phase-2",
            "owner": "Product / Memory",
            "status": "planned",
            "progress": 8,
            "target_date": "2026-10-16",
            "summary": "形成完整会议生命周期，并从记忆提炼可确认的行动项。",
            "priority": "medium",
        },
        {
            "id": "natural-recall",
            "name": "眼镜端召回与每日回顾",
            "phase": "phase-3",
            "owner": "Experience",
            "status": "planned",
            "progress": 5,
            "target_date": "2026-11-06",
            "summary": "直接问眼镜获得回答与卡片，并形成每天的记忆回顾。",
            "priority": "medium",
        },
        {
            "id": "privacy-retention",
            "name": "隐私、删除与长期保留",
            "phase": "phase-3",
            "owner": "Platform / Product",
            "status": "planned",
            "progress": 15,
            "target_date": "2026-11-13",
            "summary": "建立暂停、删除、保留策略、审计与跨设备隐私控制。",
            "priority": "high",
        },
    ]
    now = _now()
    return {
        "version": 1,
        "project": {
            "name": "随身记忆系统",
            "objective": "让用户佩戴眼镜一个下午后，能够找回真实事件、物品、谈话和承诺，并回到原始证据核对。",
            "current_phase": "phase-1",
            "manager_message": "工程闭环已成形，当前重点是把‘能跑’变成‘可信’。",
            "updated_at": now,
        },
        "phases": [
            {"id": "phase-1", "name": "真实记忆闭环", "target": "2026 Q3", "description": "采集、理解、长期记忆、Web 查看、搜索与物品召回"},
            {"id": "phase-2", "name": "人物与会议", "target": "2026 Q4", "description": "人物确认、说话人、会议生命周期、承诺与待办"},
            {"id": "phase-3", "name": "自然召回", "target": "2026 Q4", "description": "眼镜端问答、每日回顾、隐私与跨设备联动"},
        ],
        "milestones": milestones,
        "risks": [
            {"id": "risk-semantic", "title": "语义质量尚未达到发布口径", "level": "high", "owner": "AI Pipeline", "mitigation": "冻结评测集，分别完成 Caption、检索和 Last-seen Semantic Gate。"},
            {"id": "risk-device", "title": "真实眼镜 Device Gate 尚未完成", "level": "high", "owner": "Device / QA", "mitigation": "安排连续下午佩戴测试，保留脱敏标签和运行报告。"},
            {"id": "risk-stability", "title": "四小时稳定性和弱网恢复待验证", "level": "medium", "owner": "Platform", "mitigation": "执行插拔、断网、重启与依赖故障注入。"},
            {"id": "risk-scope", "title": "人物、会议与召回并行可能分散资源", "level": "medium", "owner": "Product", "mitigation": "先守住真实记忆闭环，再按阶段开放后续能力。"},
        ],
        "updates": [
            {"id": "update-initial", "created_at": now, "author": "项目组", "type": "project", "title": "建立管理层项目进度看板", "body": "已按当前 PRD 状态初始化路线图、里程碑、风险和发布边界。", "milestone_id": None},
            {"id": "update-caption", "created_at": "2026-07-20T18:00:00+08:00", "author": "Multimodal", "type": "milestone", "title": "第一人称经历理解工程合同完成", "body": "caption-only 生产代码与 Engineering Gate 已完成，06C 语义评测和真机 Gate 继续推进。", "milestone_id": "first-person-caption"},
            {"id": "update-search", "created_at": "2026-07-20T17:00:00+08:00", "author": "Retrieval / Web", "type": "milestone", "title": "Web 记忆搜索工程闭环具备", "body": "文本、图片与图文搜索页面已经具备；双链路新 Gate 仍保持 pending。", "milestone_id": "memory-search"},
        ],
    }


class ProjectTrackerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            return self._with_summary(data)

    def update_milestone(self, milestone_id: str, changes: dict[str, Any], *, author: str, note: str | None) -> dict[str, Any]:
        allowed = {"status", "progress", "owner", "target_date", "summary", "priority"}
        with self._lock:
            data = self._read()
            milestone = next((item for item in data["milestones"] if item["id"] == milestone_id), None)
            if milestone is None:
                raise KeyError(milestone_id)
            for key, value in changes.items():
                if key in allowed and value is not None:
                    milestone[key] = value
            milestone["progress"] = max(0, min(100, int(milestone.get("progress", 0))))
            if milestone.get("status") not in STATUS_LABELS:
                raise ValueError("invalid status")
            if note:
                data["updates"].insert(0, {
                    "id": f"update-{datetime.now().timestamp():.6f}".replace(".", ""),
                    "created_at": _now(),
                    "author": author or "项目组",
                    "type": "milestone",
                    "title": f"更新「{milestone['name']}」至 {milestone['progress']}%",
                    "body": note,
                    "milestone_id": milestone_id,
                })
            data["project"]["updated_at"] = _now()
            self._write(data)
            return self._with_summary(data)

    def add_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            update = {
                "id": f"update-{datetime.now().timestamp():.6f}".replace(".", ""),
                "created_at": _now(),
                "author": str(payload.get("author") or "项目组").strip(),
                "type": str(payload.get("type") or "project").strip(),
                "title": str(payload.get("title") or "项目进展更新").strip(),
                "body": str(payload.get("body") or "").strip(),
                "milestone_id": payload.get("milestone_id") or None,
            }
            data["updates"].insert(0, update)
            data["project"]["updated_at"] = update["created_at"]
            self._write(data)
            return self._with_summary(data)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            data = default_project_snapshot()
            self._write(data)
            return data
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError):
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            if self.path.exists():
                self.path.replace(backup)
            data = default_project_snapshot()
            self._write(data)
            return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    @staticmethod
    def _with_summary(data: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(data)
        milestones = result.get("milestones", [])
        overall = round(sum(int(item.get("progress", 0)) for item in milestones) / max(1, len(milestones)))
        status_counts = {status: 0 for status in STATUS_LABELS}
        for item in milestones:
            status_counts[item.get("status", "planned")] = status_counts.get(item.get("status", "planned"), 0) + 1
        for phase in result.get("phases", []):
            phase_items = [item for item in milestones if item.get("phase") == phase.get("id")]
            phase["progress"] = round(sum(item.get("progress", 0) for item in phase_items) / max(1, len(phase_items)))
            phase["milestone_count"] = len(phase_items)
        result["summary"] = {
            "overall_progress": overall,
            "completed": status_counts.get("completed", 0),
            "in_progress": status_counts.get("in_progress", 0),
            "at_risk": status_counts.get("at_risk", 0) + status_counts.get("blocked", 0),
            "planned": status_counts.get("planned", 0),
            "risk_count": len(result.get("risks", [])),
        }
        return result
