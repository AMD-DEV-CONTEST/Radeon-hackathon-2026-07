"""阶段 4 — 场景设计 agent。

任务复杂度：中 -> STRUCTURE 档(通用模型)。
产物 SceneBible 含每个场景的英文锁定提示词, 镜头注入它以保证背景一致。
"""
from __future__ import annotations

import random

from .base import Agent
from ..llm_client import TIER_STRUCTURE
from ..schemas import ChapterManifest, StoryBible, SceneBible, Scene


class SceneDesigner(Agent):
    name = "场景设计"
    tier = TIER_STRUCTURE

    def run(self, manifest: ChapterManifest, bible: StoryBible) -> SceneBible:
        locs = sorted({l for c in manifest.chapters for l in c.locations})

        if self.ctx.dry_run:
            scenes = [self._mock_scene(l, i) for i, l in enumerate(locs or ["默认场景"])]
        else:
            system = self.ctx.prompt_template("04_scene.md") or (
                "你是美术指导。为每个核心地点产出场景锁定卡 JSON 数组: "
                "{scene_id(英文), name, location, era, palette, lighting, props[], "
                "prompt_lock_en(英文,锁定空间/光线/道具), negative_prompt, forbidden_changes[]}。")
            user = f"视觉风格:{bible.visual_style}\n色调:{bible.palette}\n地点:{locs}"
            data = self.ctx.llm.chat_json(self.tier, system, user)
            arr = data if isinstance(data, list) else data.get("scenes", [])
            scenes = []
            for s in arr:
                s.setdefault("seed", random.randint(1, 2**31 - 1))
                scenes.append(Scene(**{k: v for k, v in s.items()
                                       if k in Scene.__dataclass_fields__}))

        sb = SceneBible(novel_title=manifest.novel_title, scenes=scenes)
        sb.save(self.ctx.paths.bible / "scene_bible.json")
        self.info(f"设计场景 {len(scenes)} 个")
        return sb

    def _mock_scene(self, loc: str, i: int) -> Scene:
        return Scene(
            scene_id=f"scene_{i:02d}", name=loc, location=loc, era="架空古风",
            palette="暗木色+暖烛光", lighting="窗外冷光+室内烛光",
            props=["木窗", "青瓷茶盏", "屏风"],
            prompt_lock_en=("traditional chinese teahouse interior at night, wooden window, "
                            "warm candle light, cold rain outside, song-dynasty furniture"),
            negative_prompt="modern lighting, glass facade, neon",
            forbidden_changes=["不要现代灯具"], seed=20_000 + i)
