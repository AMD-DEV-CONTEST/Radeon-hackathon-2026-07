"""Conservative offline entity extraction for chapter import.

The rule analyzer is intentionally recall-limited. It produces reviewable
ImportChangeSet candidates without pretending to have model-level semantic
understanding.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict


_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")
_CHARACTER_CONTEXT = re.compile(
    r"([\u4e00-\u9fff]{1,4})(?:问道|说道|答道|低声道|开口|问|说|答|点头|摇头|看向|沉默)"
)
_LABELED_ENTITY = re.compile(
    r"(?:角色|人物|势力|组织|地点|区域|物品|道具|规则|体系|概念)\s*[:：]\s*([^\n，。；;]{1,40})"
)

_TYPE_SUFFIXES = {
    "faction": ("调查队", "小队", "军团", "军", "派", "宗", "门", "盟", "会", "府", "国", "族", "教", "帮", "司"),
    "location": ("村", "镇", "城", "山", "岭", "谷", "河", "海", "岛", "矿", "矿区", "营地", "炭场", "铁匠铺"),
    "item": ("玉简", "灵石", "唐刀", "长刀", "短弓", "法器", "符", "盾", "剑", "刀"),
    "concept": ("筑基", "筑基后期", "筑基中期", "金丹", "金丹期", "金丹中期", "炼气", "炼气期", "神识", "灵气"),
    "system": ("网络", "系统", "反应堆", "观测阵列"),
}
_LABEL_TYPES = {
    "角色": "character", "人物": "character", "势力": "faction", "组织": "faction",
    "地点": "location", "区域": "location", "物品": "item", "道具": "item",
    "规则": "rule", "体系": "system", "概念": "concept",
}
_STOP_NAMES = {
    "他", "她", "它", "他们", "她们", "来人", "那人", "有人", "众人", "对方",
    "自己", "这里", "那里", "现在", "随后", "此刻", "已经", "没有", "只是",
    "因此", "所以", "然而", "但是", "于是", "因为", "虽然", "如果", "那么",
    "并且", "以及", "同时", "其中", "此外", "后来", "不过", "其实", "这样",
    "这种", "这个", "那个", "这些", "那些", "什么", "怎么", "为什么",
    "时候", "情况", "东西", "事情", "地方", "人员", "任务", "路线",
}
_STOP_PHRASES = {
    "这种情况", "这个时候", "与此同时", "不久之后", "在这种情况下",
}
_INTERNAL_NOISE = ("坐在", "抵达", "进入", "已经", "负责", "看见", "发现", "是")
_NOISE_PREFIXES = ("在", "于", "往", "向", "从", "到", "是", "达", "入", "经")
_LEADING_NOISE = re.compile(
    r"^(?:为什么|如果|目前|随后|此刻|现在|附近|远处|一个|一名|一支|一座|一处|这支|那支|某个|几名|大量|正式|临时|真正|负责|进入|离开|看见|发现|来自|属于|前往)+"
)
_CULTIVATION_STAGE = re.compile(r"(炼气|筑基|金丹|元婴|化神)(?:前期|中期|后期|巅峰|期|境)?")
_LOW_VALUE_SUFFIX = ("的人", "时候", "情况", "东西", "事情", "方向", "位置")


def _clean_candidate(value: str) -> str:
    value = value.strip(" \t\r\n，。！？；：:、“”‘’（）()《》<>的")
    value = _LEADING_NOISE.sub("", value)
    return value.strip("的")


def _is_denied_candidate(value: str) -> bool:
    if not value:
        return True
    if value in _STOP_NAMES or value in _STOP_PHRASES:
        return True
    if value.isdigit() or re.fullmatch(r"[\W_]+", value):
        return True
    if value.startswith(_NOISE_PREFIXES):
        return True
    if any(token in value for token in _INTERNAL_NOISE):
        return True
    if len(value) == 1 and value not in {"雪"}:
        return True
    return any(value.endswith(suffix) for suffix in _LOW_VALUE_SUFFIX)


def _sentence_snippets(text: str, title: str) -> list[str]:
    snippets = []
    for sentence in _SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        if title in sentence and sentence not in snippets:
            snippets.append(sentence[:220])
        if len(snippets) >= 2:
            break
    return snippets


class RuleBasedChapterAnalyzer:
    """Offline analyzer using labels, suffixes, repeated mentions and context verbs."""

    name = "local_rules"

    def analyze(self, chapter_text: str, chapter_index: int = 0) -> dict:
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", chapter_text or "")
        candidates: dict[str, str] = {}
        evidence = defaultdict(set)

        for match in _LABELED_ENTITY.finditer(text):
            label = match.group(0).split(match.group(1), 1)[0].split(":", 1)[0].split("：", 1)[0].strip()
            title = _clean_candidate(match.group(1))
            if 1 <= len(title) <= 40:
                candidates[title] = _LABEL_TYPES.get(label, "concept")
                evidence[title].add("label")

        character_hits = Counter(_clean_candidate(value) for value in _CHARACTER_CONTEXT.findall(text))
        for title, context_count in character_hits.items():
            mention_count = text.count(title)
            if (
                title
                and not _is_denied_candidate(title)
                and len(title) <= 4
                and (context_count >= 2 or mention_count >= 2)
            ):
                candidates.setdefault(title, "character")
                evidence[title].add("speech_or_action")

        for entity_type, suffixes in _TYPE_SUFFIXES.items():
            for suffix in sorted(suffixes, key=len, reverse=True):
                for match in re.finditer(re.escape(suffix), text):
                    if entity_type in {"location", "item", "system"} and len(suffix) >= 2:
                        candidates.setdefault(suffix, entity_type)
                        evidence[suffix].add("typed_suffix")
                    alternatives = []
                    for length in range(max(2, len(suffix)), min(10, match.end()) + 1):
                        start = match.end() - length
                        raw = text[start:match.end()]
                        if not re.fullmatch(r"[\u4e00-\u9fff]{2,10}", raw):
                            continue
                        title = _clean_candidate(raw)
                        if len(title) < 2 or _is_denied_candidate(title):
                            continue
                        alternatives.append((text.count(title), len(title), title))
                    if alternatives:
                        repeated = [item for item in alternatives if item[0] >= 2]
                        short_candidates = [item for item in alternatives if item[1] <= 6]
                        pool = repeated or short_candidates or alternatives
                        count, _, title = max(pool, key=lambda item: (item[0], item[1]))
                        if count >= 2 or len(title) <= 6:
                            candidates.setdefault(title, entity_type)
                            evidence[title].add("repeated_suffix" if count >= 2 else "typed_suffix")

        for match in _CULTIVATION_STAGE.finditer(text):
            title = _clean_candidate(match.group(0))
            if title and not _is_denied_candidate(title):
                candidates.setdefault(title, "concept")
                evidence[title].add("cultivation_stage")

        entities = []
        for title, entity_type in candidates.items():
            if _is_denied_candidate(title):
                continue
            count = text.count(title)
            snippets = _sentence_snippets(text, title)
            description_status = "evidence_only" if snippets else "missing"
            entities.append({
                "title": title,
                "type": entity_type,
                "content": "\n".join(snippets) or f"在第 {chapter_index + 1} 个分析片段中出现。",
                "tags": ["本地规则识别", *sorted(evidence[title]), description_status],
                "importance": min(10, max(3, 2 + count)),
                "description_status": description_status,
                "source_chapter": chapter_index + 1,
                "source_text": snippets[0] if snippets else "",
                "evidence_rules": sorted(evidence[title]),
                "review_status": "pending",
            })

        entity_titles = sorted(candidates, key=len, reverse=True)
        relations = []
        relation_seen = set()
        relation_patterns = (
            ("member_of", re.compile(r"(.{1,12}?)(?:加入|属于|效忠|隶属)(.{1,12})")),
            ("located_in", re.compile(r"(.{1,12}?)(?:位于|驻守于|进入)(.{1,12})")),
        )
        for sentence in _SENTENCE_SPLIT.split(text):
            present = [title for title in entity_titles if title in sentence]
            if len(present) < 2:
                continue
            for relation_type, pattern in relation_patterns:
                if not pattern.search(sentence):
                    continue
                for source in present:
                    for target in present:
                        if source == target or sentence.find(source) > sentence.find(target):
                            continue
                        key = (source, target, relation_type)
                        if key in relation_seen:
                            continue
                        relation_seen.add(key)
                        relations.append({
                            "source": source,
                            "target": target,
                            "relation_type": relation_type,
                            "description": sentence.strip()[:220],
                        })

        result = {
            "entities": entities,
            "relations": relations,
            "warnings": [
                "本地规则分析结果偏保守，可能遗漏别名、隐含关系和跨章节同一实体。",
            ],
            "analysis_mode": self.name,
        }
        from services.world_import.chapter_extractor import (
            merge_chapter_analysis_with_local_coverage,
        )

        return merge_chapter_analysis_with_local_coverage(result, text)
