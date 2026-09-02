"""端到端流水线：把 13 个 agent 用 Orchestrator 串成 小说→成片 的完整流程。

阶段级用状态机串行推进(可断点续跑); 镜头级(关键帧/视频/配音/对口型)用任务队列并行到双卡。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .context import Context
from .imports import (
    FactoryImportConflict,
    FactoryImportCorrupt,
    load_revision_snapshot,
)
from .orchestrator import Orchestrator
from .schemas import (ChapterManifest, StoryBible, CharacterBible, SceneBible,
                      ShotList, AssetRegistry)
from .agents import (NovelSplitter, StoryBibleAgent, CharacterDesigner, SceneDesigner,
                     AssetPlanner, Storyboard, AssetGenerator, KeyframeGenerator,
                     VideoGenerator, TTSAgent, LipsyncAgent, SubtitleAgent, Assembler, Reviewer)
from .runtime import atomic_write_json, validate_episode_id


class DramaPipeline:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.orch = Orchestrator(ctx)

    def run(self, novel_path: str, novel_title: str = "",
            only_episode: Optional[str] = None, max_episodes: int = 0) -> list:
        ctx, orch = self.ctx, self.orch
        ctx.check_cancelled()
        P = ctx.paths

        # ---------- 文本阶段(全书一次) ----------
        manifest = self._stage_text(orch, novel_path, novel_title)
        bible, chars, scenes = self._stage_bibles(orch, manifest)

        # ---------- 资产规划(公私分层) ----------
        orch.run_stage("asset_plan",
                       lambda: AssetPlanner(ctx).run(manifest, bible, chars, scenes))
        registry = AssetRegistry.load(P.bible / "asset_registry.json")

        # ---------- 资产阶段(全书一次, 只生成【公共资产】) ----------
        # 私有(逐集临时)资产留到该集制作时现补(见 _run_episode)。
        assets = AssetGenerator(ctx)
        orch.run_stage("char_assets",
                       lambda: assets.run_characters(chars, bible.visual_style,
                                                     only=registry.public_char_ids()))
        orch.run_stage("scene_assets",
                       lambda: assets.run_scenes(scenes, bible.visual_style,
                                                 only=registry.public_scene_ids()))
        chars = CharacterBible.load(P.bible / "character_bible.json")
        scenes = SceneBible.load(P.bible / "scene_bible.json")

        # ---------- 逐集阶段 ----------
        plan = bible.episode_plan or [{"episode_id": "E001", "chapters":
                                       [c.chapter_id for c in manifest.chapters[:1]]}]
        if max_episodes:
            plan = plan[:max_episodes]
        episodes = []
        for ep_plan in plan:
            ctx.check_cancelled()
            eid = ep_plan["episode_id"]
            if only_episode and eid != only_episode:
                continue
            episodes.append(self._run_episode(ep_plan, manifest, bible, chars, scenes))
        return episodes

    def run_from_import(
        self,
        revision_root: str | Path,
        only_episode: Optional[str] = None,
        max_episodes: int = 0,
    ) -> list:
        """Run from a confirmed immutable import, skipping source generation."""

        ctx = self.ctx
        ctx.check_cancelled()
        revision, snapshot = load_revision_snapshot(revision_root)
        if Path(revision.root).resolve() != ctx.paths.root.resolve():
            raise FactoryImportCorrupt(
                "import revision must run in its own project workspace"
            )
        manifest, bible, chars, scenes = self._materialize_import(
            revision,
            snapshot,
        )
        for stage in (
            "import_materialize",
            "split",
            "story_bible",
            "characters",
            "scenes",
            "storyboard",
        ):
            self.orch.mark_done(stage)
        registry = AssetRegistry.load(
            ctx.paths.bible / "asset_registry.json"
        )

        assets = AssetGenerator(ctx)
        self.orch.run_stage(
            "char_assets",
            lambda: assets.run_characters(
                chars,
                bible.visual_style,
                only=registry.public_char_ids(),
                preserve_existing=True,
            ),
        )
        self.orch.run_stage(
            "scene_assets",
            lambda: assets.run_scenes(
                scenes,
                bible.visual_style,
                only=registry.public_scene_ids(),
                preserve_existing=True,
            ),
        )
        chars = CharacterBible.load(
            ctx.paths.bible / "character_bible.json"
        )
        scenes = SceneBible.load(ctx.paths.bible / "scene_bible.json")

        plan = bible.episode_plan or [
            {
                "episode_id": path.name.removesuffix("_shot_list.json"),
                "chapters": [],
            }
            for path in sorted(ctx.paths.shots.glob("*_shot_list.json"))
        ]
        if max_episodes:
            plan = plan[:max_episodes]
        episodes = []
        for ep_plan in plan:
            ctx.check_cancelled()
            episode_id = ep_plan.get("episode_id")
            try:
                episode_id = validate_episode_id(episode_id)
            except ValueError:
                raise FactoryImportCorrupt(
                    "imported episode plan is invalid"
                ) from None
            if only_episode and episode_id != only_episode:
                continue
            if not (
                ctx.paths.shots / f"{episode_id}_shot_list.json"
            ).is_file():
                raise FactoryImportCorrupt(
                    "imported episode has no confirmed shot list"
                )
            episodes.append(
                self._run_episode(
                    ep_plan,
                    manifest,
                    bible,
                    chars,
                    scenes,
                )
            )
        return episodes

    def _materialize_import(self, revision, snapshot):
        ctx, paths = self.ctx, self.ctx.paths
        marker = paths.root / "import_source.json"
        if marker.exists():
            try:
                source = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise FactoryImportCorrupt(
                    "import workspace marker is invalid"
                ) from None
            if (
                source.get("revision_id") != str(revision.revision_id)
                or source.get("revision_sha256")
                != revision.revision_sha256
            ):
                raise FactoryImportConflict(
                    "import workspace belongs to a different revision"
                )
            return (
                ChapterManifest.load(
                    paths.bible / "chapter_manifest.json"
                ),
                StoryBible.load(paths.bible / "story_bible.json"),
                CharacterBible.load(
                    paths.bible / "character_bible.json"
                ),
                SceneBible.load(paths.bible / "scene_bible.json"),
            )

        documents = {
            item.document.value: json.loads(item.content_json)
            for item in snapshot.documents
        }
        required = {
            "story_bible",
            "character_bible",
            "scene_bible",
            "shot_list",
            "prompt_constraints",
        }
        if set(documents) != required:
            raise FactoryImportCorrupt(
                "import revision does not contain every factory document"
            )
        story = documents["story_bible"]
        characters = documents["character_bible"]
        scenes = documents["scene_bible"]
        shots = documents["shot_list"]
        constraints = documents["prompt_constraints"]
        episodes = shots.get("episodes")
        if not isinstance(episodes, dict) or not episodes:
            raise FactoryImportCorrupt(
                "import revision contains no confirmed shot list"
            )

        normalized_shots: dict[str, dict] = {}
        for episode_id, value in sorted(episodes.items()):
            try:
                safe_episode_id = validate_episode_id(episode_id)
            except ValueError:
                raise FactoryImportCorrupt(
                    "imported shot list has an invalid episode identifier"
                ) from None
            if (
                not isinstance(value, dict)
                or value.get("episode_id") != safe_episode_id
            ):
                raise FactoryImportCorrupt(
                    "imported shot list identity is invalid"
                )
            normalized_shots[safe_episode_id] = self._apply_prompt_constraints(
                value,
                constraints,
            )

        novel_title = str(story.get("novel_title") or "")
        manifest = {
            "novel_title": novel_title,
            "chapters": [],
        }
        episode_ids = list(normalized_shots)
        registry = {
            "novel_title": novel_title,
            "characters": [
                {
                    "asset_id": item.get("char_id"),
                    "scope": "public",
                    "episodes": episode_ids,
                }
                for item in characters.get("characters", [])
                if isinstance(item, dict)
                and isinstance(item.get("char_id"), str)
                and item["char_id"]
            ],
            "scenes": [
                {
                    "asset_id": item.get("scene_id"),
                    "scope": "public",
                    "episodes": episode_ids,
                }
                for item in scenes.get("scenes", [])
                if isinstance(item, dict)
                and isinstance(item.get("scene_id"), str)
                and item["scene_id"]
            ],
            "per_episode": {
                episode_id: {
                    "public": [
                        *[
                            item["char_id"]
                            for item in characters.get("characters", [])
                            if isinstance(item, dict)
                            and isinstance(item.get("char_id"), str)
                            and item["char_id"]
                        ],
                        *[
                            item["scene_id"]
                            for item in scenes.get("scenes", [])
                            if isinstance(item, dict)
                            and isinstance(item.get("scene_id"), str)
                            and item["scene_id"]
                        ],
                    ],
                    "private": [],
                }
                for episode_id in episode_ids
            },
        }

        atomic_write_json(paths.bible / "story_bible.json", story)
        atomic_write_json(
            paths.bible / "character_bible.json",
            characters,
        )
        atomic_write_json(paths.bible / "scene_bible.json", scenes)
        atomic_write_json(
            paths.bible / "prompt_constraints.json",
            constraints,
        )
        atomic_write_json(
            paths.bible / "import_locks.json",
            {
                "locks": [
                    item.model_dump(mode="json")
                    for item in snapshot.locked_fields
                ]
            },
        )
        atomic_write_json(
            paths.bible / "chapter_manifest.json",
            manifest,
        )
        atomic_write_json(
            paths.bible / "asset_registry.json",
            registry,
        )
        shots_root = paths.shots.resolve(strict=True)
        for episode_id, value in normalized_shots.items():
            target = shots_root / f"{episode_id}_shot_list.json"
            if target.parent.resolve(strict=True) != shots_root:
                raise FactoryImportCorrupt(
                    "imported shot list path escaped the project"
                )
            atomic_write_json(
                target,
                value,
            )
        atomic_write_json(
            marker,
            {
                "revision_id": str(revision.revision_id),
                "revision_sha256": revision.revision_sha256,
                "base_revision_id": (
                    str(revision.base_revision_id)
                    if revision.base_revision_id is not None
                    else None
                ),
                "pack_id": str(revision.pack_id),
                "pack_sha256": revision.pack_sha256,
                "plan_id": str(revision.plan_id),
                "plan_sha256": revision.plan_sha256,
            },
        )
        return (
            ChapterManifest.load(paths.bible / "chapter_manifest.json"),
            StoryBible.load(paths.bible / "story_bible.json"),
            CharacterBible.load(
                paths.bible / "character_bible.json"
            ),
            SceneBible.load(paths.bible / "scene_bible.json"),
        )

    @staticmethod
    def _apply_prompt_constraints(
        shot_list: dict,
        constraints: dict,
    ) -> dict:
        value = json.loads(json.dumps(shot_list))
        if not isinstance(constraints, dict):
            raise FactoryImportCorrupt(
                "imported prompt constraints are invalid"
            )
        suffixes: dict[str, list[str]] = {}
        for key in ("visual", "video", "negative"):
            rows = constraints.get(key, [])
            if (
                not isinstance(rows, list)
                or not all(
                    isinstance(item, str) and item.strip()
                    for item in rows
                )
            ):
                raise FactoryImportCorrupt(
                    "imported prompt constraints are invalid"
                )
            suffixes[key] = [item.strip() for item in rows]
        field_by_key = {
            "visual": "visual_prompt_en",
            "video": "video_prompt_en",
            "negative": "negative_prompt",
        }
        rows = value.get("shots")
        if not isinstance(rows, list):
            raise FactoryImportCorrupt(
                "imported shot list is invalid"
            )
        for shot in rows:
            if not isinstance(shot, dict):
                raise FactoryImportCorrupt(
                    "imported shot list is invalid"
                )
            for key, field in field_by_key.items():
                parts = []
                current = shot.get(field)
                if isinstance(current, str) and current.strip():
                    parts.append(current.strip())
                for suffix in suffixes[key]:
                    if suffix not in parts:
                        parts.append(suffix)
                shot[field] = ", ".join(parts)
        return value

    # ---------------- 文本/圣经 ----------------
    def _stage_text(self, orch, novel_path, title) -> ChapterManifest:
        path = self.ctx.paths.bible / "chapter_manifest.json"
        orch.run_stage("split",
                       lambda: NovelSplitter(self.ctx).run(novel_path, title))
        return ChapterManifest.load(path)

    def _stage_bibles(self, orch, manifest):
        ctx, P = self.ctx, self.ctx.paths
        ctx.check_cancelled()
        orch.run_stage("story_bible",
                       lambda: StoryBibleAgent(ctx).run(manifest,
                            aspect_ratio=ctx.cfg("output", "aspect_ratio", default="9:16")))
        bible = StoryBible.load(P.bible / "story_bible.json")
        orch.run_stage("characters",
                       lambda: CharacterDesigner(ctx).run(manifest, bible))
        chars = CharacterBible.load(P.bible / "character_bible.json")
        orch.run_stage("scenes",
                       lambda: SceneDesigner(ctx).run(manifest, bible))
        scenes = SceneBible.load(P.bible / "scene_bible.json")
        return bible, chars, scenes

    # ---------------- 单集 ----------------
    def _run_episode(self, ep_plan, manifest, bible, chars, scenes):
        ctx, P = self.ctx, self.ctx.paths
        eid = ep_plan["episode_id"]
        sl_path = P.shots / f"{eid}_shot_list.json"
        ctx.log.info(f"\n########## 制作 {eid} ##########")

        # 分镜
        if not sl_path.exists():
            Storyboard(ctx).run(ep_plan, manifest, bible, chars, scenes)
        sl = ShotList.load(sl_path)

        # 该集【私有(临时)资产】现补：只生成本集私有的角色/场景(权限分层——不碰公共资产)。
        reg_path = P.bible / "asset_registry.json"
        if reg_path.exists():
            priv = AssetRegistry.load(reg_path).episode_private(eid)
            if priv["characters"] or priv["scenes"]:
                ag = AssetGenerator(ctx)
                if priv["characters"]:
                    ag.run_characters(chars, bible.visual_style, only=priv["characters"])
                if priv["scenes"]:
                    ag.run_scenes(scenes, bible.visual_style, only=priv["scenes"])
                chars = CharacterBible.load(P.bible / "character_bible.json")
                scenes = SceneBible.load(P.bible / "scene_bible.json")

        orch = Orchestrator(ctx)  # 单集内部并行调度
        rv = Reviewer(ctx, chars)
        max_rounds = int(ctx.cfg("review", "qc_max_rounds", default=3))
        max_retries = int(ctx.cfg("review", "qc_max_retries", default=2))

        # 关键帧(并行) -> 质检闭环(诊断→路由→reroll/重写→只重出失败镜→复检), 直到无返工或到上限。
        kf = KeyframeGenerator(ctx, chars, scenes)
        orch.run_shots_parallel(sl, kf, ("pending",), sl_path)
        if ctx.cfg("review", "review_keyframes", default=True):
            changed = None  # 首轮查全集, 之后只复检上一轮重出的镜
            for rnd in range(max_rounds):
                recs = rv.qc_feedback(sl, scenes, write_back=True, only=changed)
                queued, _nh = rv.apply_keyframe_fixes(sl, recs, bible, scenes, max_retries)
                if not queued:
                    break
                ctx.log.info(f"[质检闭环] 关键帧第{rnd+1}轮: 重出 {len(queued)} 镜")
                orch.run_shots_parallel(sl, kf, ("pending",), sl_path)
                sl = ShotList.load(sl_path)
                changed = queued

        # I2V 视频: 先并行出"切镜头", 再按顺序出"接上一镜末帧"的连续镜头(需前一镜先成片)
        vg = VideoGenerator(ctx, sl)
        orch.run_shots_parallel(sl, vg, ("keyframe_ok",), sl_path,
                                predicate=lambda s: not s.continue_from_prev)
        orch.run_shots_sequential(sl, vg, ("keyframe_ok",), sl_path,
                                  predicate=lambda s: s.continue_from_prev)
        sl = ShotList.load(sl_path)

        # 视频质检闭环(诊断→路由→reroll/重写运动词→只重出失败 clip→复检), 直到无返工或到上限。
        if ctx.cfg("review", "review_clips", default=True):
            changed = None
            for rnd in range(max_rounds):
                recs = rv.qc_video(sl, only=changed)
                queued, _nh = rv.apply_video_fixes(sl, recs, max_retries)
                if not queued:
                    break
                ctx.log.info(f"[质检闭环] 视频第{rnd+1}轮: 重出 {len(queued)} clip")
                qset = set(queued)
                orch.run_shots_parallel(sl, vg, ("keyframe_ok",), sl_path,
                                        predicate=lambda s: s.shot_id in qset and not s.continue_from_prev)
                orch.run_shots_sequential(sl, vg, ("keyframe_ok",), sl_path,
                                          predicate=lambda s: s.shot_id in qset and s.continue_from_prev)
                sl = ShotList.load(sl_path)
                changed = queued

        # 配音(并行, 仅有台词镜头实际生成)
        tts = TTSAgent(ctx, chars)
        orch.run_shots_parallel(sl, tts, ("clip_ok",), sl_path)

        # 对口型(并行) / 非对话镜头直接置 done
        orch.run_shots_parallel(sl, LipsyncAgent(ctx), ("voice_ok",), sl_path)

        # 字幕
        srt = SubtitleAgent(ctx).run(sl)

        # 合成
        ep = Assembler(ctx).run(sl, srt)

        # 需人工复审清单: 质检到上限仍未过的镜(已用最后一版继续出片, 不丢镜)。醒目汇总给人工。
        nh = [{"shot_id": s.shot_id, "character": (s.characters[0] if s.characters else "(空镜)"),
               "note": s.qc_notes} for s in sl.shots if "[needs_human]" in (s.qc_notes or "")]
        if nh:
            (P.root / ".cache").mkdir(parents=True, exist_ok=True)
            (P.root / ".cache" / "needs_human.json").write_text(
                json.dumps({"episode": eid, "count": len(nh), "shots": nh}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            ids = [x["shot_id"] for x in nh]
            ctx.log.warning(f"⚠ 需人工复审 {len(nh)} 镜(质检多轮未过, 已用最后一版继续出片): "
                            f"{ids} → {eid} .cache/needs_human.json")

        # 成片审核(技术校验) + 可选整片【长程】视觉质检(连贯/跨镜一致/节奏)
        ep = rv.review_episode(ep)
        if ctx.cfg("review", "review_episode_vision", default=True):
            try:
                rv.qc_episode(eid, ep.final_path)
            except Exception as e:  # noqa: BLE001  长程质检失败不阻断成片
                ctx.log.warning(f"整片长程质检失败(不阻断): {e}")
        return ep
