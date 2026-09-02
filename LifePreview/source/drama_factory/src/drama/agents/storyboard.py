"""阶段 5 — 分镜 agent(把一集拆成镜头表)。

任务复杂度：中-高(导演级镜头设计) -> 默认 STRUCTURE, 可在 pipeline.yaml 调到 CREATIVE。
核心动作：为每个镜头组装 visual_prompt_en = 全局风格 + 场景锁定 + 人物锁定 + 镜头动作,
从而把“一致性锁定”机械地注入到每一张图/每一段视频, 这是一致性能落地的关键。
镜头时长控制在 3-6 秒(开源 I2V 模型的稳定区间)。
"""
from __future__ import annotations

from .base import Agent
from ..llm_client import TIER_STRUCTURE, TIER_CREATIVE, TIER_BULK
from ..schemas import (ChapterManifest, StoryBible, CharacterBible, SceneBible,
                       ShotList, Shot)


# ---------------------------------------------------------------------------
# 提示词组装(分镜与质检返工共用, 保证返工后锁定卡/全局风格仍一致)
# ---------------------------------------------------------------------------
_VISUAL_SUFFIX = "cinematic lighting, vertical 9:16, high detail, no text, no watermark"
_BASE_NEG = ("inconsistent face, bad hands, malformed hands, mutated hands, fused fingers, "
            "extra fingers, missing fingers, extra limbs, deformed, mutated, "
            "multiple panels, split screen, comic grid, contact sheet, storyboard layout, "
            "collage, tiled, blurry, watermark, text")


def build_visual_prompt(bible, scene, cast, action_en, shot_type, camera_motion) -> str:
    """全局风格 + 场景锁定 + 人物锁定 + 动作 + 景别/运镜 + 统一后缀 → 关键帧正向提示词。
    分镜首次组装与质检返工重写都走这里, 确保返工只动动作/景别, 锁定卡与画风不漂移。"""
    parts = [getattr(bible, "visual_style", "") if bible else ""]
    if scene:
        parts.append(scene.prompt_lock_en)
    for c in (cast or []):
        parts.append(c.prompt_lock_en)
    parts.append(action_en)
    parts += [(shot_type or "medium") + " shot", (camera_motion or "static") + " camera", _VISUAL_SUFFIX]
    return ", ".join(p for p in parts if p)


def build_video_prompt(camera_motion, action_en) -> str:
    return ", ".join(filter(None, [(camera_motion or "static") + " camera", action_en,
                                   "coherent motion, natural movement, cinematic"]))


def build_negative(scene, cast) -> str:
    return ", ".join(filter(None, [_BASE_NEG,
                                   scene.negative_prompt if scene else "",
                                   *[c.negative_prompt for c in (cast or [])]]))


class Storyboard(Agent):
    name = "分镜"
    tier = TIER_STRUCTURE

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._tr_cache: dict[str, str] = {}  # 中文动作->英文 翻译缓存(单次运行内去重)

    def run(self, episode: dict, manifest: ChapterManifest, bible: StoryBible,
            chars: CharacterBible, scenes: SceneBible) -> ShotList:
        eid = episode["episode_id"]
        if self.ctx.cfg("storyboard", "use_creative_model", default=False):
            self.tier = TIER_CREATIVE

        chap_ids = episode.get("chapters", [])
        chap_text = "\n\n".join(
            f"[{c.chapter_id} {c.title}]\n{c.raw_text or c.summary}"
            for c in manifest.chapters if c.chapter_id in chap_ids)[:8000]

        min_d = self.ctx.cfg("video", "min_shot_sec", default=3)
        max_d = self.ctx.cfg("video", "max_shot_sec", default=6)

        if self.ctx.dry_run:
            raw_shots = self._mock_shots(eid, chars, scenes, n=3)
        else:
            system = self.ctx.prompt_template("05_storyboard.md") or (
                "你是短剧导演与分镜师。把本集剧情拆成镜头数组 JSON, 每个镜头: "
                "{chapter_id(来源章节id), scene_id, characters[](用char_id), shot_type, "
                f"camera_motion, duration_sec({min_d}-{max_d}), action(中文), "
                "action_en(对应英文运动/动作描述, 供图像/视频模型用), "
                "dialogue(台词,无则空), speaker(char_id), emotion, audio_notes}。"
                "竖屏构图, 镜头短、动作单一, 强情绪, 对话镜头优先近景。")
            roles = {c.char_id: c.name for c in chars.characters}
            places = {s.scene_id: s.name for s in scenes.scenes}
            user = (f"集:{eid} 钩子:{episode.get('hook','')}\n"
                    f"可用角色:{roles}\n可用场景:{places}\n剧情:\n{chap_text}")
            data = self.ctx.llm.chat_json(self.tier, system, user)
            raw_shots = data if isinstance(data, list) else data.get("shots", [])

        shots: list[Shot] = []
        for i, rs in enumerate(raw_shots, 1):
            sid = f"{eid}_S{i:03d}"
            shot = self._compose_shot(sid, eid, rs, bible, chars, scenes, episode)
            shots.append(shot)

        # 诊断: 分镜引用了未建卡的角色 → 这些镜头会无 IPAdapter 锚点(人物不一致根因之一)
        known = {c.char_id for c in chars.characters}
        unknown = sorted({cid for s in shots for cid in s.characters if cid not in known})
        if unknown:
            self.warn(f"分镜引用了未建卡的角色(将无锚/无 IPAdapter): {unknown}; "
                      f"已建卡角色: {sorted(known)}")

        sl = ShotList(episode_id=eid, novel_title=manifest.novel_title, shots=shots)
        sl.save(self.ctx.paths.shots / f"{eid}_shot_list.json")
        self.info(f"{eid}: 生成 {len(shots)} 个镜头")
        return sl

    def _compose_shot(self, sid, eid, rs, bible, chars, scenes, episode=None) -> Shot:
        """把全局风格+场景锁定+人物锁定 注入英文提示词(一致性核心)。"""
        scene = scenes.get(rs.get("scene_id", "")) if rs.get("scene_id") else None
        cast = [chars.get(cid) for cid in rs.get("characters", []) if chars.get(cid)]

        # 优先用模型直出的 action_en; 缺失时(非 dry-run)走轻量翻译兜底。
        action_en = rs.get("action_en", "") or self._to_en(rs.get("action", ""))

        # 全局风格+场景锁定+人物锁定 注入(与质检返工共用 build_*，保证一致)。
        visual = build_visual_prompt(bible, scene, cast,
                                     action_en, rs.get("shot_type", "medium"),
                                     rs.get("camera_motion", "static"))
        # 负面词强化：①手部专项(SDXL 烂手重灾区) ②多格/分屏(防把竖屏构图误解成漫画分镜格)。
        neg = build_negative(scene, cast)
        dialogue = rs.get("dialogue", "") or ""
        needs_lip = bool(dialogue) and rs.get("shot_type", "") in (
            "close-up", "medium close-up", "medium", "")

        # chapter_id: 模型未标注时回退到本集首个来源章节(episode["chapters"][0])。
        chapters = (episode or {}).get("chapters") or []
        chapter_id = rs.get("chapter_id", "") or (chapters[0] if chapters else "")

        return Shot(
            shot_id=sid, episode_id=eid, chapter_id=chapter_id,
            scene_id=rs.get("scene_id", ""),
            duration_sec=float(rs.get("duration_sec", 4)),
            shot_type=rs.get("shot_type", "medium"),
            camera_motion=rs.get("camera_motion", "static"),
            characters=rs.get("characters", []),
            action=rs.get("action", ""), dialogue=dialogue,
            speaker=rs.get("speaker", ""), emotion=rs.get("emotion", ""),
            visual_prompt_en=visual,
            video_prompt_en=build_video_prompt(rs.get("camera_motion", "static"), action_en),
            negative_prompt=neg, audio_notes=rs.get("audio_notes", ""),
            needs_lipsync=needs_lip, status="pending",
            continue_from_prev=bool(rs.get("continue_from_prev", False)),
            anchor_mode=(rs.get("anchor_mode", "") or "").strip().lower(),
        )

    def _mock_shots(self, eid, chars, scenes, n=3) -> list[dict]:
        cid = chars.characters[0].char_id if chars.characters else "char_00"
        sid = scenes.scenes[0].scene_id if scenes.scenes else "scene_00"
        out = []
        for i in range(n):
            # 桩里直接给 action_en, dry-run 不联网也能产出完整英文提示词;
            # chapter_id 故意不填, 由 _compose_shot 回退到本集首章兜底。
            out.append({
                "scene_id": sid, "characters": [cid],
                "shot_type": "medium close-up", "camera_motion": "slow push in",
                "duration_sec": 4, "action": "抬头望向窗外，雨水滑落",
                "action_en": "looks up toward the window, raindrops sliding down the glass",
                "dialogue": "这场雨，来得太不是时候了。" if i == 0 else "",
                "speaker": cid, "emotion": "忧虑", "audio_notes": "雨声, 低音弦乐",
                "continue_from_prev": i == 2})
        return out

    def _to_en(self, zh: str) -> str:
        """中文动作/运动描述 -> 简短英文运动短语(action_en 缺失时的兜底翻译)。

        - 空串或 dry-run 直接返回 ""(dry-run 绝不联网, 且 mock 译文是垃圾)。
        - 走 BULK 档(便宜/本地)翻译; 单次运行内按原文缓存, 避免重复翻译。
        - 异常安全: 任何失败都返回 ""(绝不让流水线因翻译崩溃)。
        """
        if not zh or self.ctx.dry_run:
            return ""
        if zh in self._tr_cache:
            return self._tr_cache[zh]
        system = ("Translate this Chinese film action/motion description into a short, "
                  "vivid English motion phrase for a video generation model. "
                  "Output only the English phrase, no quotes/explanation.")
        try:
            en = (self.ctx.llm.chat(TIER_BULK, system, zh) or "").strip()
        except Exception:  # noqa: BLE001 兜底翻译不可阻断流水线
            en = ""
        self._tr_cache[zh] = en
        return en
