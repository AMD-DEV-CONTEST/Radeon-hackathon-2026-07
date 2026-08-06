"""阶段 1 — 拆书 agent。

任务复杂度：低-中(规则+轻量模型即可) -> 使用 BULK 档(本地轻量模型)。
先用规则按标题/空行/序号粗切，再让本地模型为每章生成摘要与要素抽取。
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import Agent
from ..input_loader import load_text
from ..llm_client import TIER_BULK
from ..schemas import ChapterManifest, Chapter

_CHAPTER_PAT = re.compile(
    r"第(?P<zh_number>[零一二三四五六七八九十百千0-9]+)[章回节][^\r\n]*|"
    r"(?:Chapter\s+|CH)(?P<en_number>\d+)[^\r\n]*",
    re.IGNORECASE,
)

_ZH_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_ZH_UNITS = {"十": 10, "百": 100, "千": 1000}


def _chapter_number(match: re.Match[str]) -> int | None:
    english = match.group("en_number")
    if english is not None:
        return int(english)
    token = match.group("zh_number")
    if token is None:
        return None
    if token.isascii() and token.isdigit():
        return int(token)
    if all(character in _ZH_DIGITS for character in token):
        return int("".join(str(_ZH_DIGITS[character]) for character in token))
    total = 0
    current = 0
    for character in token:
        if character in _ZH_DIGITS:
            current = _ZH_DIGITS[character]
        elif character in _ZH_UNITS:
            total += (current or 1) * _ZH_UNITS[character]
            current = 0
        else:
            return None
    return total + current


def _continuous_chapter_matches(
    matches: list[re.Match[str]],
) -> list[re.Match[str]]:
    """Keep a monotonic chapter sequence and ignore incidental references.

    Some downloaded TXT books lose the newline immediately before a chapter
    heading.  Matching only line starts then merges dozens of chapters, while
    accepting every ``第 X 章`` occurrence would split on prose references.
    Once the first real heading is found after the content marker, requiring
    consecutive chapter numbers provides a bounded recovery signal.
    """

    if not matches:
        return []
    first_number = _chapter_number(matches[0])
    if first_number is None:
        return matches
    selected = [matches[0]]
    expected = first_number + 1
    for match in matches[1:]:
        number = _chapter_number(match)
        if number == expected:
            selected.append(match)
            expected += 1
    return selected


def split_novel_text(text: str) -> list[tuple[str, str]]:
    """Split Chinese/English chapter headings or fall back to 4k windows.

    Chinese chapter titles normally continue immediately after ``章``/``回``;
    a word-boundary assertion there is incorrect because both Chinese
    characters are Unicode word characters.
    """

    content_marker = text.find("章节内容开始")
    search_start = content_marker + len("章节内容开始") if content_marker >= 0 else 0
    matches = _continuous_chapter_matches(
        list(_CHAPTER_PAT.finditer(text, search_start))
    )
    if not matches:
        chunk = 4000
        parts = [text[index : index + chunk] for index in range(0, len(text), chunk)]
        return [(f"片段{index + 1}", part) for index, part in enumerate(parts)]
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(0).strip()
        result.append((heading, text[match.start() : end]))
    return result


class NovelSplitter(Agent):
    name = "拆书"
    tier = TIER_BULK

    def run(self, novel_path: str | Path, novel_title: str = "") -> ChapterManifest:
        text = load_text(novel_path)  # 支持 txt/md/docx/epub/pdf 多格式输入
        title = novel_title or Path(novel_path).stem
        raw_chapters = self._rule_split(text)
        self.info(f"规则拆分得到 {len(raw_chapters)} 章")

        chapters: list[Chapter] = []
        for i, (head, body) in enumerate(raw_chapters, 1):
            cid = f"CH{i:03d}"
            meta = self._analyze(head, body)
            chapters.append(Chapter(
                chapter_id=cid,
                title=meta.get("title", head[:40]) or head[:40],
                summary=meta.get("summary", ""),
                characters=meta.get("characters", []),
                locations=meta.get("locations", []),
                conflict=meta.get("conflict", ""),
                emotion_arc=meta.get("emotion_arc", ""),
                raw_text=body.strip(),
            ))
        manifest = ChapterManifest(novel_title=title, chapters=chapters)
        manifest.save(self.ctx.paths.bible / "chapter_manifest.json")
        return manifest

    def _rule_split(self, text: str) -> list[tuple[str, str]]:
        return split_novel_text(text)

    def _analyze(self, head: str, body: str) -> dict:
        if self.ctx.dry_run:
            return {"title": head[:30], "summary": body.strip()[:120],
                    "characters": ["主角"], "locations": ["未知地点"],
                    "conflict": "示例冲突", "emotion_arc": "平静→紧张"}
        system = self.ctx.prompt_template("01_split.md") or (
            "你是中文小说影视化改编助理。基于给定章节文本，"
            "抽取要素并输出 JSON: {title, summary(200字内), characters[], "
            "locations[], conflict, emotion_arc}。不要改写剧情。")
        return self.ctx.llm.chat_json(self.tier, system, f"标题:{head}\n\n正文:\n{body[:6000]}")
