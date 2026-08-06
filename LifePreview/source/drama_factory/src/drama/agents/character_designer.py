"""阶段 3 — 人物设计 agent(一致性的源头)。

任务复杂度：高(决定每个角色的锁定卡, 直接影响全剧一致性) -> CREATIVE 档。
关键产物 prompt_lock_en: 每个角色的英文锁定提示词, 后续所有镜头都注入它,
配合参考图(asset_generator)+ ControlNet/Kontext 实现“同一个人”。
"""
from __future__ import annotations

import random

from .base import Agent
from ..llm_client import TIER_CREATIVE
from ..schemas import ChapterManifest, StoryBible, CharacterBible, Character


class CharacterDesigner(Agent):
    name = "人物设计"
    tier = TIER_CREATIVE

    def run(self, manifest: ChapterManifest, bible: StoryBible) -> CharacterBible:
        # 汇总全书出场人物
        names = sorted({n for c in manifest.chapters for n in c.characters})
        ch_brief = "\n".join(f"{c.title}: {c.summary}" for c in manifest.chapters[:20])

        if self.ctx.dry_run:
            chars = [self._mock_char(n, i) for i, n in enumerate(names or ["主角", "反派"])]
        else:
            system = self.ctx.prompt_template("03_character.md") or (
                "你是短剧人物设定与选角导演。为每个主要角色产出锁定卡 JSON 数组, 元素含: "
                "{char_id(英文小写下划线), name, age, role, appearance(中文), "
                "outfit_default, personality, "
                "prompt_lock_en(英文,锁定脸型/发型/服装/标志特征,贯穿所有镜头), "
                "negative_prompt(英文,禁止变化), voice_profile(中文音色描述), "
                "forbidden_changes[]}。外貌要具体到可复现(发型/脸型/标志痣/服装主色)。")
            user = (f"视觉风格:{bible.visual_style}\n人物列表:{names}\n剧情概要:\n{ch_brief}")
            data = self.ctx.llm.chat_json(self.tier, system, user)
            arr = data if isinstance(data, list) else data.get("characters", [])
            chars = []
            for c in arr:
                c.setdefault("seed", random.randint(1, 2**31 - 1))
                chars.append(Character(**{k: v for k, v in c.items()
                                          if k in Character.__dataclass_fields__}))

        cb = CharacterBible(novel_title=manifest.novel_title, characters=chars)
        cb.save(self.ctx.paths.bible / "character_bible.json")
        self.info(f"设计角色 {len(chars)} 个: {[c.name for c in chars]}")
        return cb

    def _mock_char(self, name: str, i: int) -> Character:
        return Character(
            char_id=f"char_{i:02d}", name=name, age=24 + i, role="主角" if i == 0 else "配角",
            appearance="鹅蛋脸，细眉，右眼下方小痣，黑色长发低发髻",
            outfit_default="青灰色长衫，银色发簪",
            personality="冷静克制",
            prompt_lock_en=("young chinese woman, oval face, thin eyebrows, small mole "
                            "under right eye, long black hair in low bun, gray-blue robe"),
            negative_prompt="short hair, modern clothes, western face, inconsistent face",
            voice_profile="清冷女声，语速偏慢",
            forbidden_changes=["不要短发", "不要现代服装"],
            seed=10_000 + i,
        )
