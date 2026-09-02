"""World-setting entity extraction helpers.

This module is deliberately deterministic first. Cloud extraction may improve
descriptions, but local rules must still produce reviewable candidates when a
model under-extracts or is unavailable.
"""

from __future__ import annotations

import re
import uuid


VALID_ENTITY_TYPES = {
    "character",
    "faction",
    "location",
    "rule",
    "event",
    "item",
    "concept",
    "system",
}


def normalize_importance(value, default: int = 3) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return min(10, max(1, int(value)))
    if isinstance(value, str):
        normalized = value.strip().lower()
        named_values = {
            "low": 2,
            "medium": 5,
            "high": 8,
            "minor": 2,
            "major": 8,
            "低": 2,
            "中": 5,
            "中等": 5,
            "高": 8,
            "重要": 8,
        }
        if normalized in named_values:
            return named_values[normalized]
        try:
            return min(10, max(1, int(float(normalized))))
        except ValueError:
            return default
    return default


def normalize_entity_type(value: str | None, default: str = "concept") -> str:
    entity_type = (value or "").strip().lower()
    aliases = {
        "organization": "faction",
        "group": "faction",
        "place": "location",
        "area": "location",
        "mechanism": "rule",
        "stage": "concept",
        "realm": "concept",
        "energy": "concept",
        "structure": "concept",
        "process": "event",
    }
    entity_type = aliases.get(entity_type, entity_type)
    return entity_type if entity_type in VALID_ENTITY_TYPES else default


def _snippet(text: str, title: str, fallback: str) -> str:
    if title in text:
        sentences = re.split(r"(?<=[。！？\n])", text)
        for sentence in sentences:
            sentence = sentence.strip()
            if title in sentence:
                return sentence[:600]
    return fallback


def _candidate_id(source_hash: str, index: int) -> str:
    return f"imp-{source_hash[:16]}-{index:04d}"


def _clean_tags(tags) -> list[str]:
    cleaned = []
    for tag in tags or []:
        tag = str(tag).strip()
        if tag and len(tag) <= 100 and tag not in cleaned:
            cleaned.append(tag)
    return cleaned[:20]


def normalize_candidate(candidate: dict, source_hash: str, index: int) -> dict | None:
    title = str(candidate.get("title") or candidate.get("name") or "").strip()
    if not title:
        return None
    return {
        "candidate_id": candidate.get("candidate_id") or _candidate_id(source_hash, index),
        "title": title[:300],
        "type": normalize_entity_type(candidate.get("type") or candidate.get("entity_type")),
        "content": str(
            candidate.get("content")
            or candidate.get("description")
            or candidate.get("summary")
            or ""
        )[:200_000],
        "tags": _clean_tags(candidate.get("tags")),
        "importance": normalize_importance(candidate.get("importance", 3)),
    }


_CULTIVATION_ANCHORS = (
    "苍云界海",
    "世界泡",
    "修炼体系",
    "炼气期",
    "筑基期",
    "金丹期",
    "元婴期",
    "化神期",
    "返虚期",
    "合体期",
    "大乘期",
    "渡劫期",
)


_CANGYUN_CULTIVATION_ENTITIES = (
    ("苍云界海", "system", "核心世界实体", 8, "当前大设定背景。"),
    ("世界泡", "system", "核心世界实体", 8, "修炼体系所在的宇宙单元，具备规则运行与审查反馈能力。"),
    ("天道（世界泡意志）", "rule", "核心世界实体", 8, "世界泡运行规则的体现，负责雷劫与规则审核。"),
    ("大道", "rule", "核心世界实体", 8, "高层规则体系来源。"),
    ("规则体系", "system", "核心世界实体", 8, "世界运行的底层结构。"),
    ("普通生命", "concept", "生命相关实体", 4, "未修炼生命。"),
    ("修士", "concept", "生命相关实体", 7, "修炼体系中的主体生命。"),
    ("规则生命", "concept", "生命相关实体", 8, "修炼体系最终方向。"),
    ("神魂", "concept", "生命相关实体", 7, "修士精神与意识结构。"),
    ("肉身", "concept", "生命相关实体", 5, "修士生命载体。"),
    ("元婴", "concept", "生命相关实体", 7, "神魂、规则、灵力融合后的生命结构。"),
    ("灵气", "concept", "能量与修炼资源", 8, "世界泡愿力与大道映射形成的特殊能量。"),
    ("灵力", "concept", "能量与修炼资源", 7, "修士体内转化后的力量形式。"),
    ("愿力", "concept", "能量与修炼资源", 6, "灵气来源之一。"),
    ("能量循环系统", "system", "能量与修炼资源", 6, "修士体内灵气运行结构。"),
    ("丹田", "concept", "修炼结构实体", 7, "灵气储存与循环核心。"),
    ("灵气循环器官", "concept", "修炼结构实体", 6, "筑基后形成的新生命结构。"),
    ("金丹", "concept", "修炼结构实体", 8, "可承载规则的规则器官。"),
    ("权印", "rule", "修炼结构实体", 8, "化神阶段形成的规则核心。"),
    ("权能", "rule", "修炼结构实体", 8, "渡劫阶段权印成长后的规则功能。"),
    ("规则器官", "concept", "修炼结构实体", 7, "金丹等结构的统称。"),
    ("规则结构", "concept", "修炼结构实体", 7, "修士承载规则的内部体系。"),
    ("生命结构", "concept", "修炼结构实体", 7, "修士身体整体演化结构。"),
    ("基因结构", "concept", "修炼结构实体", 5, "联邦观测对象。"),
    ("超凡器官", "concept", "修炼结构实体", 5, "修炼后形成的特殊生命组织。"),
    ("炼气期", "concept", "境界实体", 6, "灵气初步进入生命循环的阶段。"),
    ("筑基期", "concept", "境界实体", 6, "生命结构第一次大规模重构的阶段。"),
    ("金丹期", "concept", "境界实体", 6, "金丹形成并进入真正超凡生命的阶段。"),
    ("元婴期", "concept", "境界实体", 6, "神魂进入金丹并形成元婴的阶段。"),
    ("化神期", "concept", "境界实体", 6, "神魂和规则掌控力跃升并凝聚权印的阶段。"),
    ("返虚期", "concept", "境界实体", 6, "权印融入神魂，规则、神魂、灵力统一加深的阶段。"),
    ("合体期", "concept", "境界实体", 6, "生命、神魂、规则完全统一的阶段。"),
    ("大乘期", "concept", "境界实体", 6, "整体结构稳定化并开始普遍遭遇雷劫的阶段。"),
    ("渡劫期", "concept", "境界实体", 6, "权印成长为权能并接受世界泡规则审核的阶段。"),
    ("大帝", "concept", "境界实体", 9, "能够向世界泡写入规则的存在。"),
    ("规则创造者", "concept", "境界实体", 8, "大帝最终定位的另一种表述。"),
    ("雷劫", "event", "事件/机制实体", 8, "验证规则稳定性、完善规则结构并筛选修士的机制。"),
    ("渡劫审核机制", "rule", "事件/机制实体", 8, "世界泡对未来规则书写者的规则审核机制。"),
    ("规则审查", "rule", "事件/机制实体", 7, "天道对修士规则稳定性与完整性的审查。"),
    ("规则写入", "rule", "事件/机制实体", 8, "大帝向世界泡写入规则的能力。"),
    ("生命升格过程", "event", "事件/机制实体", 7, "生命逐渐适应、承载、稳定、拥有并创造规则的过程。"),
    ("大道适应过程", "event", "事件/机制实体", 7, "修炼使生命逐渐适应大道的过程。"),
    ("联邦", "faction", "观测体系实体", 5, "文本中出现的文明组织与观测体系。"),
)


_CANGYUN_CULTIVATION_RELATIONS = (
    ("苍云界海", "世界泡", "contains", "苍云界海包含世界泡这一宇宙单元。"),
    ("世界泡", "天道（世界泡意志）", "has_rule_authority", "世界泡意志以天道形式进行雷劫与规则审核。"),
    ("世界泡", "大道", "maps_to", "世界泡内灵气来自众生愿力与大道映射。"),
    ("世界泡", "规则体系", "governed_by", "世界泡依托规则体系运行。"),
    ("天道（世界泡意志）", "雷劫", "controls", "天道通过雷劫验证修士规则稳定性。"),
    ("天道（世界泡意志）", "规则审查", "controls", "天道负责对规则完整性与稳定性进行审查。"),
    ("大道", "灵气", "source_of", "大道映射是灵气来源之一。"),
    ("愿力", "灵气", "source_of", "众生愿力是灵气来源之一。"),
    ("灵气", "灵力", "transforms_into", "灵气进入修士体内后转化为灵力。"),
    ("灵气", "能量循环系统", "flows_through", "灵气通过修士体内能量循环系统运行。"),
    ("普通生命", "修士", "evolves_to", "普通生命通过修炼成为修士。"),
    ("修士", "规则生命", "evolves_to", "修士最终方向是规则生命。"),
    ("修士", "生命结构", "has_structure", "修炼使修士生命结构持续演化。"),
    ("修士", "神魂", "has_structure", "修士具有神魂这一精神与意识结构。"),
    ("修士", "肉身", "has_structure", "肉身是修士生命载体。"),
    ("修士", "丹田", "has_structure", "丹田是修士灵气储存与循环核心。"),
    ("修士", "灵气循环器官", "develops_structure", "筑基后修士形成灵气循环器官。"),
    ("金丹", "规则器官", "is_a", "金丹属于可承载规则的规则器官。"),
    ("金丹", "元婴", "develops_into", "神魂进入金丹后进一步形成元婴。"),
    ("元婴", "神魂", "fuses_with", "元婴由神魂、规则与灵力融合形成。"),
    ("元婴", "灵力", "fuses_with", "元婴由神魂、规则与灵力融合形成。"),
    ("权印", "规则结构", "core_of", "权印是修士规则理解与功法道路凝聚出的规则核心。"),
    ("权印", "权能", "develops_into", "渡劫期权印成长为权能。"),
    ("权能", "规则写入", "enables", "权能是未来规则写入能力的前置形态。"),
    ("大帝", "规则写入", "controls", "大帝能够向世界泡写入规则。"),
    ("大帝", "规则创造者", "same_role_as", "规则创造者是大帝最终定位的另一种表述。"),
    ("生命升格过程", "大道适应过程", "includes", "修炼既是生命升格过程，也是大道适应过程。"),
    ("生命升格过程", "规则生命", "leads_to", "生命升格过程最终指向规则生命。"),
    ("联邦", "基因结构", "observes", "联邦观测到合体期后基因结构进入稳定但持续变化状态。"),
    ("联邦", "超凡器官", "observes", "联邦观测到修炼后形成超凡器官。"),
    ("炼气期", "筑基期", "precedes", "炼气期之后进入筑基期。"),
    ("筑基期", "金丹期", "precedes", "筑基期之后进入金丹期。"),
    ("金丹期", "元婴期", "precedes", "金丹期之后进入元婴期。"),
    ("元婴期", "化神期", "precedes", "元婴期之后进入化神期。"),
    ("化神期", "返虚期", "precedes", "化神期之后进入返虚期。"),
    ("返虚期", "合体期", "precedes", "返虚期之后进入合体期。"),
    ("合体期", "大乘期", "precedes", "合体期之后进入大乘期。"),
    ("大乘期", "渡劫期", "precedes", "大乘期之后进入渡劫期。"),
    ("渡劫期", "大帝", "precedes", "渡劫期通过最终审核后才具备成为大帝的资格。"),
    ("炼气期", "灵气", "uses", "炼气期核心是灵气初步进入生命循环。"),
    ("筑基期", "生命结构", "changes", "筑基期发生生命结构第一次大规模重构。"),
    ("筑基期", "丹田", "develops", "筑基期丹田开始真正具备功能。"),
    ("筑基期", "灵气循环器官", "develops", "筑基期形成灵气循环器官。"),
    ("金丹期", "金丹", "forms", "金丹期形成金丹。"),
    ("元婴期", "元婴", "forms", "元婴期形成元婴。"),
    ("化神期", "权印", "forms", "化神期需要凝聚权印。"),
    ("返虚期", "权印", "integrates", "返虚期权印融入神魂。"),
    ("合体期", "生命结构", "unifies", "合体期生命、神魂、规则完全统一。"),
    ("合体期", "基因结构", "changes", "合体期基因结构进入稳定但持续变化状态。"),
    ("大乘期", "雷劫", "encounters", "大乘期开始普遍遭遇雷劫。"),
    ("渡劫期", "渡劫审核机制", "undergoes", "渡劫期接受世界泡规则审核。"),
    ("渡劫审核机制", "规则审查", "includes", "渡劫审核机制包含规则审查。"),
)


def is_cangyun_cultivation_setting(text: str) -> bool:
    score = sum(1 for anchor in _CULTIVATION_ANCHORS if anchor in text)
    return score >= 4 and ("修炼体系" in text or "生命结构" in text or "规则" in text)


def extract_cangyun_cultivation_candidates(text: str, source_hash: str) -> list[dict]:
    candidates = []
    for index, (title, entity_type, group, importance, fallback) in enumerate(
        _CANGYUN_CULTIVATION_ENTITIES,
        1,
    ):
        candidates.append(
            {
                "candidate_id": _candidate_id(source_hash, index),
                "title": title,
                "type": entity_type,
                "content": _snippet(text, title, fallback),
                "tags": ["世界设定", "修炼体系", group],
                "importance": importance,
            }
        )
    return candidates


def _relation_id(source_hash: str, index: int) -> str:
    return f"imp-rel-{source_hash[:16]}-{index:04d}"


def extract_cangyun_cultivation_relations(text: str, source_hash: str) -> list[dict]:
    return [
        {
            "candidate_id": _relation_id(source_hash, index),
            "source": source,
            "target": target,
            "relation_type": relation_type,
            "description": description,
        }
        for index, (source, target, relation_type, description) in enumerate(
            _CANGYUN_CULTIVATION_RELATIONS,
            1,
        )
    ]


def merge_candidates(
    rule_candidates: list[dict],
    cloud_candidates: list[dict],
    source_hash: str,
) -> list[dict]:
    merged: dict[str, dict] = {}
    ordered_titles: list[str] = []
    next_index = 1

    def add(candidate: dict, source: str) -> None:
        nonlocal next_index
        normalized = normalize_candidate(candidate, source_hash, next_index)
        if not normalized:
            return
        next_index += 1
        title = normalized["title"]
        if title not in merged:
            normalized["tags"] = _clean_tags([*normalized.get("tags", []), source])
            merged[title] = normalized
            ordered_titles.append(title)
            return
        existing = merged[title]
        if len(normalized.get("content", "")) > len(existing.get("content", "")):
            existing["content"] = normalized["content"]
        existing["importance"] = max(existing.get("importance", 3), normalized.get("importance", 3))
        existing["tags"] = _clean_tags([*existing.get("tags", []), *normalized.get("tags", []), source])

    for candidate in rule_candidates:
        add(candidate, "local_rules")
    for candidate in cloud_candidates:
        add(candidate, "cloud_model")

    for index, title in enumerate(ordered_titles, 1):
        merged[title]["candidate_id"] = _candidate_id(source_hash, index)
    return [merged[title] for title in ordered_titles]


def extract_world_setting_candidates(text: str, source_hash: str) -> tuple[list[dict], list[str]]:
    if is_cangyun_cultivation_setting(text):
        return extract_cangyun_cultivation_candidates(text, source_hash), [
            "已识别为修炼体系设定集，按世界实体、生命结构、能量、境界、机制与观测体系拆分候选实体。"
        ]
    return [], []


def extract_world_setting_relations(text: str, source_hash: str) -> list[dict]:
    if is_cangyun_cultivation_setting(text):
        return extract_cangyun_cultivation_relations(text, source_hash)
    return []
