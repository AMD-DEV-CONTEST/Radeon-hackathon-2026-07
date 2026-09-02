"""阶段 2 — 故事圣经 agent。

任务复杂度：高(全局创意决策, 决定整部剧的风格基调与分集) -> CREATIVE 档(最强模型)。
产物 StoryBible 中的 visual_style 会作为全局 prompt 注入到每一个镜头，保证全剧统一调性。
"""
from __future__ import annotations

import re

from .base import Agent
from ..llm_client import TIER_CREATIVE
from ..schemas import ChapterManifest, StoryBible

# 全局画风里【不该出现】的具体地点/车辆/房间/道具名词(它会被注入每一镜→挡风玻璃/办公室加到所有镜头)。
_STYLE_BANNED = re.compile(
    r"\b(windshield|windscreen|dashboard|rear[\s-]?view|cockpit|cabin|steering\s+wheel|"
    r"car|vehicle|truck|bus|mirror|"
    r"office|bedroom|room|kitchen|hallway|corridor|apartment|indoor|desk|cubicle|door|"
    r"street|sidewalk|alley|storefront|shop|store|"
    r"smartphone|phone|laptop|computer|screen|television|monitor)\b",
    re.IGNORECASE)


def sanitize_visual_style(style: str) -> tuple[str, list[str]]:
    """剥掉全局画风里混进的【具体地点/道具】子句(逗号分隔)。全局画风只该有画风/光质/色调/镜头/情绪,
    含挡风玻璃/办公室/方向盘等会被强行注入每一镜(连闪回都变车里)。返回(清洗后, 被剥子句)。
    失败兜底: 若会剥空则原样保留, 只告警。"""
    if not style:
        return style, []
    kept, dropped = [], []
    for p in (x.strip() for x in style.split(",")):
        if not p:
            continue
        (dropped if _STYLE_BANNED.search(p) else kept).append(p)
    cleaned = ", ".join(kept)
    return (cleaned, dropped) if cleaned.strip() else (style, [])


class StoryBibleAgent(Agent):
    name = "故事圣经"
    tier = TIER_CREATIVE

    def run(self, manifest: ChapterManifest, episodes: int = 0,
            aspect_ratio: str = "9:16") -> StoryBible:
        ch_brief = "\n".join(
            f"{c.chapter_id} {c.title}: {c.summary}" for c in manifest.chapters)

        if self.ctx.dry_run:
            data = {
                "logline": f"《{manifest.novel_title}》示例一句话故事",
                "genre": "古风悬疑", "tone": "克制、冷峻",
                "visual_style": "cinematic, moody lighting, film grain, "
                                "ancient chinese aesthetic, vertical composition",
                "palette": "暗木色 + 暖烛光 + 青灰雨色",
                "episode_plan": [
                    {"episode_id": "E001", "title": "示例第一集",
                     "chapters": ["CH001"], "hook": "悬念钩子"}],
            }
        else:
            system = self.ctx.prompt_template("02_story_bible.md") or (
                "你是资深短剧总编剧与视觉总监。基于章节清单，产出故事圣经 JSON: "
                "{logline, genre, tone, visual_style(英文,贯穿全剧的统一视觉风格关键词), "
                "palette, episode_plan:[{episode_id, title, chapters[], hook}]}。"
                "竖屏短剧每集 1-3 分钟，节奏快、强钩子、每集留悬念。")
            user = (f"小说:《{manifest.novel_title}》 画幅:{aspect_ratio} "
                    f"目标集数:{episodes or '自动'}\n\n章节清单:\n{ch_brief}")
            data = self.ctx.llm.chat_json(self.tier, system, user)

        # 全局画风消毒: 剥掉混进来的具体地点/道具(否则注入每一镜→哪儿都像在车里)。
        vstyle, dropped = sanitize_visual_style(data.get("visual_style", ""))
        if dropped:
            self.warn(f"全局画风剥除 {len(dropped)} 个地点/道具子句(应只描述画风, 不含具体场景): {dropped}")

        bible = StoryBible(
            novel_title=manifest.novel_title,
            logline=data.get("logline", ""),
            genre=data.get("genre", ""),
            tone=data.get("tone", ""),
            visual_style=vstyle,
            palette=data.get("palette", ""),
            aspect_ratio=aspect_ratio,
            episode_plan=data.get("episode_plan", []),
        )
        bible.save(self.ctx.paths.bible / "story_bible.json")
        self.info(f"分集规划: {len(bible.episode_plan)} 集")
        return bible
