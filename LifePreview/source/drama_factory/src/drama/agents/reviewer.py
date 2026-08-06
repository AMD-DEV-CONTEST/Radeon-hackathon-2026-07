"""阶段 13 — 审核 agent(多模态质检)。

两级审核:
  1) 镜头级(可选): 用 VISION 档模型对关键帧打分(人物像不像/构图/有无崩坏),
     低分镜头标记返工。
  2) 成片级: 技术校验(时长/分辨率/有无黑帧/字幕) + 抽帧视觉评估, 出质检报告。

任务复杂度: 高(需要审美与多模态判断) -> VISION 档。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .base import Agent
from .storyboard import build_visual_prompt, build_video_prompt, build_negative
from ..llm_client import TIER_VISION, TIER_STRUCTURE
from ..seeding import derive_legacy_seed, derive_reroll_seed
from ..schemas import ShotList, Episode, CharacterBible

try:
    from ..utils.ffmpeg import probe_duration
except Exception:  # noqa: BLE001
    def probe_duration(_p):  # type: ignore
        return 0.0


class Reviewer(Agent):
    name = "审核"
    tier = TIER_VISION

    def __init__(self, ctx, chars: CharacterBible | None = None):
        super().__init__(ctx)
        self.chars = chars
        self.threshold = ctx.cfg("review", "shot_pass_threshold", default=0.6)
        # 视觉质检后端: sdk=直调 GLM-4.6V(headless, 默认) / mcp(需 Claude 客户端, 未内置) /
        # local_vlm(本地 VLM, 未来)。当前仅 sdk 内置实现; 其它值回退 sdk 并告警。
        self.vision_backend = (ctx.cfg("review", "vision_backend", default="sdk") or "sdk").lower()
        if self.vision_backend != "sdk":
            self.warn(f"vision_backend={self.vision_backend} 暂未内置, 回退 sdk(直调 GLM-4.6V)")
            self.vision_backend = "sdk"

    def _qcp(self, filename: str, fallback: str) -> str:
        """质检/重写系统提示词: 优先 prompts/<filename>(可版本化、可编辑), 缺失回退内联常量。"""
        return self.ctx.prompt_template(filename) or fallback

    # ---- 镜头级关键帧打分 ----
    def review_keyframes(self, shot_list: ShotList) -> list[str]:
        to_rework = []
        if not self.ctx.cfg("review", "review_keyframes", default=True):
            return to_rework
        for shot in shot_list.shots:
            if not shot.keyframe_path:
                continue
            res = self._score_keyframe(shot)
            shot.qc_score = float(res.get("score", 0))
            shot.qc_notes = "; ".join(res.get("issues", []))
            if shot.qc_score < self.threshold:
                shot.status = "pending"  # 退回重出关键帧
                to_rework.append(shot.shot_id)
        shot_list.save(self.ctx.paths.shots / f"{shot_list.episode_id}_shot_list.json")
        if to_rework:
            self.warn(f"关键帧质检不合格({len(to_rework)}): {to_rework}")
        return to_rework

    def _score_keyframe(self, shot) -> dict:
        if self.ctx.dry_run:
            return {"score": 0.9, "issues": [], "pass": True}
        c = self.chars.get(shot.characters[0]) if (self.chars and shot.characters) else None
        system = ("你是 AI 短剧质检。判断关键帧是否符合: 人物特征与设定一致、无肢体/脸部崩坏、"
                  "构图适配竖屏。输出 JSON {score:0-1, issues:[], pass:bool}。")
        ref = (c.appearance + " / " + c.prompt_lock_en) if c else ""
        imgs = [shot.keyframe_path] + ((c.ref_images[:1]) if c else [])
        user = f"角色设定: {ref}\n镜头动作: {shot.action}\n请对比参考图与关键帧打分。"
        try:
            return self.ctx.llm.vision_score(system, user, [p for p in imgs if p])
        except Exception as e:  # noqa: BLE001
            self.warn(f"视觉打分失败({shot.shot_id}): {e}")
            return {"score": 1.0, "issues": [], "pass": True}

    # ---- 自动化质检反馈(分数 + 根因 + 如何改) ----
    def qc_feedback(self, shot_list: ShotList, scenes=None, write_back: bool = True,
                    only: list[str] | None = None) -> list[dict]:
        """对已出关键帧的镜头做"自动化质检反馈"：不只打分, 还给【根因分类 + 如何改】。

        混合两条通道(各取所长):
          ① 文本一致性(glm-5.1, 强): 一次看全集, 抓 动作↔场景↔画面 自相矛盾
             (如动作'下车摔门'=车外 却要求'车内特写'; 动作'闪回办公室' 却 scene_id=车内)。
          ② 视觉(glm-4v): 逐镜比 关键帧↔角色锚↔设定文字, 抓 锚图与设定不一致 / 解剖崩坏 /
             身份漂移 / 背景不符。
        结果落盘 projects/<p>/.cache/kf_qc.json; write_back 时把 fix 写进 shot.qc_notes、
        overall/5 写进 shot.qc_score(仅反馈, 不改 status, 不触发返工)。返回逐镜反馈列表。
        """
        only_set = set(only) if only else None
        shots = [s for s in shot_list.shots if s.keyframe_path
                 and (only_set is None or s.shot_id in only_set)]
        if not shots:
            return []
        text_map = self._text_consistency(shots, scenes)        # 通道① 批量文本
        out = []
        for s in shots:
            vis = self._vision_feedback(s, scenes)               # 通道② 逐镜视觉
            rec = self._merge_feedback(s, vis, text_map.get(s.shot_id, {}), scenes)
            out.append(rec)
            if write_back:
                s.qc_score = round(rec["overall"] / 5.0, 2)
                s.qc_notes = rec["fix"] or s.qc_notes
        cache = self.ctx.paths.root / ".cache"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "kf_qc.json").write_text(
            json.dumps({"episode": shot_list.episode_id, "shots": out},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        if write_back:
            shot_list.save(self.ctx.paths.shots / f"{shot_list.episode_id}_shot_list.json")
        n_review = sum(1 for r in out if r["verdict"] == "review")
        self.info(f"质检反馈完成: {len(out)} 镜, 需复审 {n_review}。→ .cache/kf_qc.json")
        return out

    def _scene_desc(self, scenes, scene_id: str) -> str:
        if not scenes or not scene_id:
            return scene_id or ""
        s = scenes.get(scene_id) if hasattr(scenes, "get") else None
        if not s:
            return scene_id
        return f"{scene_id}（{getattr(s,'name','') or ''} {getattr(s,'location','') or ''}）".strip()

    def _text_consistency(self, shots, scenes) -> dict:
        """通道①: 一次性扫全集, 找 动作↔场景↔画面 自相矛盾的镜头。返回 {shot_id: {...}}。"""
        if self.ctx.dry_run:
            return {}
        rows = []
        for s in shots:
            rows.append({
                "shot_id": s.shot_id,
                "shot_type": s.shot_type,
                # scene 留空=故意不锁场景、地点由画面提示词承载(闪回/异地的正确做法), 标注清楚防误判。
                "scene": self._scene_desc(scenes, s.scene_id) or
                         "(留空:不锁场景,地点由画面提示词给出——闪回/异地的正确处理,勿判矛盾)",
                "action": s.action,
                "visual": (s.visual_prompt_en or "")[-220:],   # 取尾部(人物/动作锁定更靠后)
            })
        _fb = (
            "你是短剧分镜一致性审查员。下面是本集每个镜头的 动作/场景/景别/画面提示词摘要。"
            "只挑出【自相矛盾、会让关键帧出错】的镜头, 三类重点:\n"
            "1) 地点矛盾: 动作发生在某处, 但 scene_id/画面写的是【另一个具体地点】"
            "(如 动作'下车、车外摔门' 但画面写 'inside car / 车内特写')。\n"
            "★重要例外: scene 为'(留空…)'表示**故意不锁场景、地点已由画面提示词承载**(闪回/异地的正确做法)。"
            "这种情况**不算矛盾, 不要输出**——只要画面提示词里已包含该地点(如 flashback, empty office)即视为正确。"
            "只有 scene **非空**且与动作地点明显冲突, 才算地点矛盾。\n"
            "2) 时空矛盾: 动作是'闪回/回忆/另一场景', 但 scene_id 仍**错误地锁在当前场景**(如 动作'闪回办公室' 但 scene_id=车内)。"
            "若 scene 已留空, 则闪回已被正确处理, 不要判矛盾。\n"
            "3) 不可成帧: 动作是一段**过程/纯声音/速度特效**, 无法用一张静帧表达"
            "(如'画面加速''传出声音'); '坐进后座''转头''微笑'这类**单一瞬间动作是可以成帧的, 不要误判**。\n"
            "对每个有问题的镜头输出对象: {shot_id, conflict_type(one of: 地点矛盾/时空矛盾/不可成帧),"
            " detail(中文,一句), fix(中文,一句:具体改 scene_id / 改画面提示词 / 改写动作 哪一个、改成什么)}。"
            "没问题的镜头不要输出。只输出 JSON 数组 []。")
        system = self._qcp("08_qc_consistency.md", _fb)
        user = json.dumps(rows, ensure_ascii=False)
        try:
            res = self.ctx.llm.chat_json(TIER_STRUCTURE, system, user)
        except Exception as e:  # noqa: BLE001
            self.warn(f"文本一致性检查失败: {e}")
            return {}
        arr = res if isinstance(res, list) else (res.get("shots") or res.get("items") or [])
        return {r["shot_id"]: r for r in arr if isinstance(r, dict) and r.get("shot_id")}

    _VIS_SYS = (
        "你是极严格的AI短剧关键帧质检员, 必须挑刺、不许一律给5分。给你[关键帧]、[角色锚图]"
        "(可能还有[场景锚图])和角色设定文字。逐项核对并只输出JSON:\n"
        '{wardrobe:0-5, identity:0-5, scene:0-5, anatomy:0-5, overall:0-5,'
        ' anchor_text_consistent:bool, issues:[中文短标签], fix:str}。\n'
        "要点: ①先判断[角色锚图]本身是否符合[设定文字](例:锚图穿西装戴眼镜, 但设定写皮夹克且没提眼镜"
        "=不一致, anchor_text_consistent=false, 并在issues写'锚图与设定不符')。"
        "②关键帧人物的 服装/眼镜/发型/脸型 是否同时对得上[设定文字]和[锚图], 对不上要扣分写明。"
        "③anatomy: 手指/手/脸/肢体/姿态有无崩坏或违反物理(如人趴在仪表台/悬空)。"
        "④scene: 背景是否符合[场景锚图]/设定。fix给一句具体中文怎么改。")

    _VIS_SYS_EMPTY = (
        "你是严格的【空镜(无人物)】关键帧质检员。给你[关键帧](可能还有[场景锚图])。"
        "这是没有人物的场景/空镜, 不要评判身份或服装。逐项核对并只输出JSON:\n"
        '{scene:0-5, anatomy:0-5, overall:0-5, issues:[中文短标签], fix:str}。\n'
        "scene=背景/构图是否符合[场景锚图]与场景设定; anatomy=有无崩坏/穿帮/多余人物乱入/文字水印/畸形物体。"
        "画面正常的空镜应给高分。fix给一句具体中文怎么改(没问题就留空)。")

    def _vision_feedback(self, shot, scenes) -> dict:
        """通道②: 逐镜视觉比对。人物镜返回 wardrobe/identity/scene/anatomy/overall/anchor_text_consistent;
        空镜(无角色)只返回 scene/anatomy/overall(不评身份/服装)。"""
        if self.ctx.dry_run:
            return {"overall": 5, "anatomy": 5, "identity": 5, "scene": 5,
                    "wardrobe": 5, "anchor_text_consistent": True, "issues": [], "fix": ""}
        c = self.chars.get(shot.characters[0]) if (self.chars and shot.characters) else None
        sc = scenes.get(shot.scene_id) if (scenes and hasattr(scenes, "get") and shot.scene_id) else None
        sc_anchor = (sc.ref_images[0] if (sc and getattr(sc, "ref_images", None)) else "")
        if c is None:
            # 空镜: 只比关键帧 + 场景锚, 只判 scene/anatomy。
            imgs = [shot.keyframe_path] + ([sc_anchor] if sc_anchor else [])
            order = "第一张=关键帧" + ("、第二张=场景锚图" if sc_anchor else "")
            user = (f"镜头动作(空镜): {shot.action}\n场景: {self._scene_desc(scenes, shot.scene_id)}\n"
                    f"{order}。这是空镜, 只评场景与画面是否崩坏。")
            sys_p = self._qcp("07_qc_keyframe_empty.md", self._VIS_SYS_EMPTY)
        else:
            imgs = [shot.keyframe_path] + (c.ref_images[:1] if c.ref_images else []) + \
                   ([sc_anchor] if sc_anchor else [])
            order = "第一张=关键帧" + ("、第二张=角色锚图" if c.ref_images else "") + \
                    ("、最后一张=场景锚图" if sc_anchor else "")
            user = (f"角色设定文字: {c.prompt_lock_en}\n镜头动作: {shot.action}\n场景: "
                    f"{self._scene_desc(scenes, shot.scene_id)}\n{order}。逐项核对后打分。")
            sys_p = self._qcp("06_qc_keyframe.md", self._VIS_SYS)
        try:
            r, raw = self.ctx.llm.vision_score(sys_p, user, [p for p in imgs if p], return_raw=True)
            if isinstance(r, dict):
                r["_raw"] = raw          # GLM-4.6V 原始输出, 供 Web 展示"原始反馈"
                return r
            return {"_raw": raw}
        except Exception as e:  # noqa: BLE001
            self.warn(f"视觉质检失败({shot.shot_id}): {e}")
            return {}

    @staticmethod
    def _to5(v, default=4):
        try:
            return max(0, min(5, int(round(float(v)))))
        except (TypeError, ValueError):
            return default

    def _merge_feedback(self, shot, vis: dict, txt: dict, scenes) -> dict:
        """把 文本一致性 + 视觉 两路合并成一条反馈: 定根因优先级 + 汇总 fix + verdict。
        人物镜与空镜分别处理(空镜不评身份/服装/锚一致)。"""
        is_empty = not shot.characters
        scene = self._to5(vis.get("scene"))
        anatomy = self._to5(vis.get("anatomy"))
        issues = list(vis.get("issues") or [])
        fixes = []

        def _apply_text_conflict(cur_overall):
            root = {"地点矛盾": "action_scene_conflict", "时空矛盾": "action_scene_conflict",
                    "不可成帧": "action_unstageable"}.get(txt.get("conflict_type"), "storyboard_conflict")
            issues.insert(0, f"分镜矛盾:{txt['conflict_type']}")
            if txt.get("detail"):
                issues.append(txt["detail"])
            if txt.get("fix"):
                fixes.append("【改分镜】" + txt["fix"])
            return root, min(cur_overall, 2)

        if is_empty:
            # 空镜: 只看 场景 + 解剖(+文本一致性, 如 S017 '画面加速' 不可成帧)。不评身份/服装/锚。
            wardrobe = identity = None
            overall = self._to5(vis.get("overall"), default=min(scene, anatomy))
            if txt.get("conflict_type"):
                root, overall = _apply_text_conflict(overall)
            elif anatomy <= 2:
                root = "model_artifact"
                fixes.append("【重出】空镜出现穿帮/多余人物/畸形, 换种子重出。")
            elif overall >= 4:
                root = "ok"
            else:
                root = "minor"
        else:
            wardrobe = self._to5(vis.get("wardrobe"))
            identity = self._to5(vis.get("identity"))
            overall = self._to5(vis.get("overall"), default=min(wardrobe, identity, scene, anatomy))
            anchor_ok = vis.get("anchor_text_consistent", True)
            # 根因优先级: 分镜矛盾(文本) > 锚↔设定不符 > 解剖崩坏 > 身份/服装漂移 > ok
            if txt.get("conflict_type"):
                root, overall = _apply_text_conflict(overall)
            elif anchor_ok is False:
                root = "anchor_bible_mismatch"
                issues.insert(0, "锚图与角色设定不一致")
                fixes.append("【对齐锚↔设定】把角色锚图重生成成与 prompt_lock_en 一致, 或反过来改 prompt_lock_en;"
                             " 关键帧本身多半没错。")
                overall = min(overall, 3)
            elif anatomy <= 2:
                root = "model_artifact"
                fixes.append("【重出/升步数】手部或姿态崩坏, 换种子重出, 或把该镜 qwen_steps 调到 8、加手部负向词。")
            elif min(identity, wardrobe) <= 2:
                root = "identity_drift"
                fixes.append("【加固身份】角色锚图换更清晰的正脸/特征近照, 或在画面提示词里强调关键特征(眼镜/发型/服装)。")
            elif overall >= 4:
                root = "ok"
            else:
                root = "minor"

        if vis.get("fix") and root != "ok":
            fixes.append(vis["fix"])
        verdict = ("review" if (overall <= 2 or root in
                                ("action_scene_conflict", "action_unstageable",
                                 "anchor_bible_mismatch", "model_artifact"))
                   else "good" if (root == "ok") else "minor")
        return {
            "shot_id": shot.shot_id,
            "character": (shot.characters[0] if shot.characters else "(空镜)"),
            "scene_id": shot.scene_id,
            "scores": {"wardrobe": wardrobe, "identity": identity, "scene": scene, "anatomy": anatomy},
            "overall": overall,
            "root_cause": root,
            "issues": [i for i in issues if i],
            "fix": " ".join(fixes).strip(),
            "verdict": verdict,
            "raw": (vis.get("_raw") or "")[:4000],   # GLM-4.6V 原始反馈(Web 展示用)
        }

    # ---- 路由 + GLM-5.1 重写 + 应用修复(P0b 路由 + P1 B方案; 内化的质检闭环) ----
    @staticmethod
    def _route_kf(rec: dict) -> str:
        """把关键帧质检结论映射到可实际消除根因的动作。"""
        if rec.get("verdict") in ("good", "minor"):
            return "pass"
        # 锚图与角色锁定卡互相冲突是资产层问题。单镜 reprompt 只会重写动作/取景，
        # 不会改变公共角色锚或锁定卡，继续重出必然重复同一个冲突并浪费 GPU。
        if rec.get("root_cause") == "anchor_bible_mismatch":
            return "human"
        return "reroll" if rec.get("root_cause") == "model_artifact" else "reprompt"

    def _import_prompt_constraints(self) -> dict[str, list[str]]:
        """读取附件级提示词约束；导入任务损坏时从不可变 source 恢复或阻断。"""
        empty = {"visual": [], "video": [], "negative": []}

        def load(path: Path) -> dict[str, list[str]] | None:
            if not path.is_file():
                return None
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return None
            if not isinstance(value, dict):
                return None
            out: dict[str, list[str]] = {}
            for key in ("visual", "video", "negative"):
                rows = value.get(key, [])
                if not isinstance(rows, list) or any(
                    not isinstance(item, str) or not item.strip()
                    for item in rows
                ):
                    return None
                out[key] = [item.strip() for item in rows]
            return out

        primary = self.ctx.paths.bible / "prompt_constraints.json"
        loaded = load(primary)
        if loaded is not None:
            return loaded
        imported = (self.ctx.paths.root / "import_source.json").is_file()
        if not imported:
            return empty
        immutable = self.ctx.paths.root / "source" / "prompt_constraints.json"
        loaded = load(immutable)
        if loaded is not None:
            self.warn("工作区导入提示词约束损坏，已从不可变 source 副本恢复")
            return loaded
        raise RuntimeError(
            "imported prompt constraints are missing or corrupt in both copies"
        )

    def _reapply_import_prompt_constraints(self, shot, *keys: str) -> None:
        """质检重写后重新附加不可丢失的附件级约束，并保证幂等。"""
        field_by_key = {
            "visual": "visual_prompt_en",
            "video": "video_prompt_en",
            "negative": "negative_prompt",
        }
        constraints = self._import_prompt_constraints()
        for key in keys:
            field = field_by_key[key]
            current = str(getattr(shot, field, "") or "").strip()
            parts = [current] if current else []
            for suffix in constraints[key]:
                if suffix not in current:
                    parts.append(suffix)
            setattr(shot, field, ", ".join(parts))

    _REWRITE_KF_SYS = (
        "你是短剧分镜师, 按质检意见【重写一个镜头的画面字段】以修掉问题, 但**严格保持人物/场景锁定与"
        "全局画风不变**(那些由系统注入, 你只描述这一镜的动作与取景)。只输出 JSON:\n"
        '{action_en, shot_type, camera_motion, anchor_mode, video_action_en, reason}。\n'
        "规则: ①只改导致问题的部分; action_en=该镜【可见动作/取景】的简短英文(空镜写环境/运动, 不写人物外貌)。\n"
        "②若构图必须大幅偏离任何参考图(道具微距/景深反转/把人虚化成剪影/锚图里没有的元素/一次性自由空镜),"
        " 把 anchor_mode 设为 'none'; 否则保持原 anchor_mode。\n"
        "③shot_type∈{wide,medium,medium close-up,close-up,extreme close-up};"
        " camera_motion∈{static,slow push in,pull out,pan left,pan right,handheld,tilt up}。\n"
        "④video_action_en=该镜视频里【明确可见的运动】英文(避免静止: 给具体运镜或主体动作)。")

    def rewrite_keyframe(self, shot, rec: dict, bible, scenes) -> dict:
        """GLM-5.1 按质检诊断重写【语义字段】(动作/景别/运镜/锚点), 再用 build_* 重组提示词
        (锁定卡/画风不动)。直接改写 shot 的 visual_prompt_en/video_prompt_en/shot_type/...; 返回原始 JSON。"""
        cast = [self.chars.get(c) for c in shot.characters if self.chars and self.chars.get(c)] \
            if self.chars else []
        scene = scenes.get(shot.scene_id) if (scenes and hasattr(scenes, "get") and shot.scene_id) else None
        if self.ctx.dry_run:
            data = {"action_en": "rewritten action", "shot_type": shot.shot_type,
                    "camera_motion": shot.camera_motion, "anchor_mode": shot.anchor_mode or "",
                    "video_action_en": "rewritten motion", "reason": "dry"}
        else:
            payload = {
                "shot_id": shot.shot_id, "action_zh": shot.action,
                "scene_id": shot.scene_id, "characters": shot.characters,
                "char_locks_en": [c.prompt_lock_en for c in cast],
                "scene_lock_en": (scene.prompt_lock_en if scene else ""),
                "current": {"shot_type": shot.shot_type, "camera_motion": shot.camera_motion,
                            "anchor_mode": shot.anchor_mode or "", "visual_prompt_en": shot.visual_prompt_en},
                "qc": {"root_cause": rec.get("root_cause"), "issues": rec.get("issues"), "fix": rec.get("fix")},
            }
            try:
                data = self.ctx.llm.chat_json(
                    TIER_STRUCTURE, self._qcp("11_rewrite_keyframe.md", self._REWRITE_KF_SYS),
                    json.dumps(payload, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                self.warn(f"重写失败({shot.shot_id}), 保留原提示词: {e}")
                return {}
        if not isinstance(data, dict):
            return {}
        action_en = (data.get("action_en") or "").strip()
        if data.get("shot_type"):
            shot.shot_type = data["shot_type"]
        if data.get("camera_motion"):
            shot.camera_motion = data["camera_motion"]
        am = (data.get("anchor_mode") or "").strip().lower()
        if am in ("dual", "char", "scene", "none"):
            shot.anchor_mode = am
        if action_en:                      # 用 build_* 重组(锁定卡/画风不漂移)
            shot.visual_prompt_en = build_visual_prompt(bible, scene, cast, action_en,
                                                        shot.shot_type, shot.camera_motion)
            shot.video_prompt_en = build_video_prompt(
                shot.camera_motion, (data.get("video_action_en") or action_en))
            self._reapply_import_prompt_constraints(
                shot, "visual", "video", "negative")
        return data

    def apply_keyframe_fixes(self, shot_list: ShotList, recs: list[dict], bible, scenes,
                             max_retries: int = 2) -> tuple[list[str], list[str]]:
        """按质检结论改修并把待重出镜置 pending(已通过的不动)。返回 (重出队列, needs_human)。
        reroll→换 keyframe_seed; reprompt→GLM-5.1 重写; 超 max_retries→needs_human。"""
        by_id = {s.shot_id: s for s in shot_list.shots}
        queued, needs_human = [], []
        for rec in recs:
            s = by_id.get(rec.get("shot_id"))
            if not s:
                continue
            route = self._route_kf(rec)
            if route == "pass":
                continue
            if route == "human":
                s.qc_notes = (
                    "[needs_human] 角色锚图与锁定卡冲突，单镜重出无法修复: "
                    f"{rec.get('fix', '')}"
                )[:300]
                needs_human.append(s.shot_id)
                continue
            if s.retries >= max_retries:
                # 到重试上限: 保留【最后一版关键帧】(status 维持 keyframe_ok)继续出视频, 只在
                # qc_notes 标记待人工——无人值守跑要产出完整集, 不能因 QC 严格就丢镜。
                s.qc_notes = f"[needs_human] 质检{max_retries}次仍不过(保留最后一版继续出视频): {rec.get('fix', '')}"[:300]
                needs_human.append(s.shot_id)
                continue
            s.status = "pending"
            if route == "reroll":
                parent_seed = int(s.keyframe_seed) or derive_legacy_seed(
                    "keyframe",
                    s.shot_id,
                ).resolved_seed
                s.keyframe_seed = derive_reroll_seed(
                    parent_resolved_seed=parent_seed,
                    reroll_index=s.retries + 1,
                ).resolved_seed
            else:                                   # reprompt → GLM-5.1 重写
                self.rewrite_keyframe(s, rec, bible, scenes)
            s.qc_notes = (rec.get("fix") or "")[:300]
            s.retries += 1
            queued.append(s.shot_id)
        shot_list.save(self.ctx.paths.shots / f"{shot_list.episode_id}_shot_list.json")
        if queued or needs_human:
            self.info(f"关键帧返工: 重出 {queued} needs_human={needs_human or '无'}")
        return queued, needs_human

    # ---- 视频片段质检(整段上传 glm-5v-turbo; 超限滑窗; 失败回退抽帧) ----
    _VID_SYS = (
        "你是AI短剧【视频片段】质检员, 必须挑刺、不许一律给5分。给你同一镜头**按时间先后**抽的若干帧。"
        "判断【动态质量】, 只输出JSON:\n"
        '{motion:0-5, physics:0-5, temporal:0-5, artifact:0-5, overall:0-5, issues:[中文短标签], fix:str}。\n'
        "motion=运动是否自然(有无滑步/抖动/瞬移/慢镜诡异); "
        "physics=有无违反物理(穿模/肢体形变/物体凭空出现或消失/重力错误); "
        "temporal=帧间一致性(人物脸/身材/服装/背景跨帧是否稳定, 不忽大忽小/变脸/闪现); "
        "artifact=崩坏/重影/鬼影/闪烁/糊。fix给一句中文怎么改。")

    def qc_video(self, shot_list: ShotList, only: list[str] | None = None) -> list[dict]:
        """逐镜【动态质检】: 直接把视频传给 glm-5v-turbo(原生看视频)判 运动/物理/时序/崩坏。
        片段超上传上限(review.video_max_mb)→ 按上限拆成【重叠滑动窗口】逐段查、取最差汇总;
        视频上传失败 → 回退抽帧多图。结果落盘 .cache/clip_qc.json。无片段→返回空。拆窗/抽帧需 ffmpeg。
        only: 只查这些 shot_id(返工后只复检重出的镜)。"""
        only_set = set(only) if only else None
        shots = [s for s in shot_list.shots if (s.final_clip_path or s.clip_path)
                 and (only_set is None or s.shot_id in only_set)]
        cache = self.ctx.paths.root / ".cache"
        cache.mkdir(parents=True, exist_ok=True)
        seg_dir = cache / "_qc_segs"
        max_bytes = int(float(self.ctx.cfg("review", "video_max_mb", default=18)) * 1024 * 1024)
        win = float(self.ctx.cfg("review", "video_window_sec", default=4.0))
        overlap = float(self.ctx.cfg("review", "video_overlap_sec", default=1.0))
        out = []
        for s in shots:
            clip = s.final_clip_path or s.clip_path
            if not clip or not os.path.exists(clip):
                continue
            size = os.path.getsize(clip)
            if size <= max_bytes:
                segs, windowed = [clip], False                  # 整段直接上传
            else:
                # 超限: 先【降画质】试图整段塞进上限(保住长程时序), 不行再滑窗。
                ds = self._downscale_to_fit(clip, seg_dir / s.shot_id / "ds.mp4", max_bytes)
                if ds and os.path.getsize(ds) <= max_bytes:
                    segs, windowed = [ds], False
                else:
                    segs = self._split_windows(ds or clip, win, overlap, seg_dir / s.shot_id)
                    windowed = True
                    if not segs:
                        out.append({"shot_id": s.shot_id, "character": (s.characters[0] if s.characters else "(空镜)"),
                                    "windows": 0, "scores": {}, "overall": 0, "root_cause": "split_failed",
                                    "issues": [f"片段 {size // (1024 * 1024)}MB 超上限且降画质/拆窗均失败(缺 ffmpeg?)"],
                                    "fix": "确认 ffmpeg 在 PATH, 或调大 review.video_max_mb", "verdict": "review"})
                        continue
            seg_vis = [self._video_vis_one(seg, s) for seg in segs]
            out.append(self._merge_video(s, seg_vis, len(segs), windowed))
        (cache / "clip_qc.json").write_text(
            json.dumps({"episode": shot_list.episode_id, "shots": out},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        n_rev = sum(1 for r in out if r["verdict"] == "review")
        self.info(f"视频质检完成: {len(out)} 镜, 需复审 {n_rev}。→ .cache/clip_qc.json")
        return out

    def _video_vis_one(self, seg: str, shot) -> dict:
        """对一段视频(整段或一个滑窗)取一次视觉判分: 先传视频, 失败回退抽帧多图。"""
        if self.ctx.dry_run:
            return {"motion": 5, "physics": 5, "temporal": 5, "artifact": 5,
                    "overall": 5, "issues": [], "fix": ""}
        vid_sys = self._qcp("09_qc_video.md", self._VID_SYS)
        user = (f"镜头 {shot.shot_id} 动作: {shot.action}\n这是该镜的一段视频, 判断动态质量(运动/物理/时序/崩坏)。")
        try:
            r, raw = self.ctx.llm.vision_video_score(vid_sys, user, seg, return_raw=True)
            if isinstance(r, dict) and r:
                r["_raw"] = raw          # GLM-4.6V 原始散文(Web 展示"原始反馈")
                return r
        except Exception as e:  # noqa: BLE001
            self.warn(f"视频上传质检失败({shot.shot_id}), 回退抽帧: {e}")
        frames = self._extract_frames(seg, 6, self.ctx.paths.root / ".cache" / "_qc_frames" / shot.shot_id)
        if not frames:
            return {}
        try:
            r, raw = self.ctx.llm.vision_score(vid_sys, user + " 按时间先后给出若干帧。", frames, return_raw=True)
            if isinstance(r, dict):
                r["_raw"] = raw
                return r
            return {}
        except Exception as e:  # noqa: BLE001
            self.warn(f"抽帧质检也失败({shot.shot_id}): {e}")
            return {}

    def _downscale_to_fit(self, src: str, dst, max_bytes: int) -> str | None:
        """逐级降画质(分辨率↓帧率↓crf↑)重编码到 dst, 直到 <= max_bytes; 返回 dst(取到的最小版本),
        缺 ffmpeg → None。用于把"总视频/长片"压到上传上限内、保住长程时序整段上传。"""
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # (高, 帧率, crf) 由轻到重
        ladders = [(720, 12, 28), (480, 10, 30), (360, 8, 32), (288, 6, 34), (240, 4, 36)]
        best = None
        for h, fps, crf in ladders:
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(src), "-vf", f"scale=-2:{h},fps={fps}",
                     "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast", "-an", str(dst)],
                    capture_output=True, text=True, errors="replace")
            except FileNotFoundError:
                self.warn("找不到 ffmpeg, 无法降画质。")
                return None
            except Exception:  # noqa: BLE001
                continue
            if dst.exists() and dst.stat().st_size > 0:
                best = str(dst)
                if dst.stat().st_size <= max_bytes:
                    return best                                  # 已塞进上限, 用这一级
        return best                                              # 最小一级仍超限也返回(调用方再判)

    def _split_windows(self, clip: str, win: float, overlap: float, outdir: Path) -> list[str]:
        """把视频切成重叠滑动窗口(每段 ~win 秒, 步进 win-overlap), 返回片段路径; 缺 ffmpeg → []。"""
        dur = 0.0
        try:
            dur = float(probe_duration(clip)) or 0.0
        except Exception:  # noqa: BLE001
            dur = 0.0
        if dur <= 0:
            dur = 6.0
        outdir.mkdir(parents=True, exist_ok=True)
        step = max(0.5, win - overlap)
        segs, i, start = [], 0, 0.0
        while start < dur - 0.05:
            dst = outdir / f"w{i:02d}.mp4"
            try:
                subprocess.run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{win:.3f}",
                                "-i", str(clip), "-c", "copy", "-avoid_negative_ts", "make_zero", str(dst)],
                               capture_output=True, text=True, errors="replace")
                if not (dst.exists() and dst.stat().st_size > 0):  # 关键帧对不齐时 -c copy 会空 → 重编码
                    subprocess.run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{win:.3f}",
                                    "-i", str(clip), "-c:v", "libx264", "-crf", "28",
                                    "-preset", "veryfast", "-an", str(dst)],
                                   capture_output=True, text=True, errors="replace")
                if dst.exists() and dst.stat().st_size > 0:
                    segs.append(str(dst))
            except FileNotFoundError:
                self.warn("找不到 ffmpeg, 无法拆窗。")
                return []
            except Exception:  # noqa: BLE001
                pass
            i += 1
            start += step
        return segs

    def _extract_frames(self, clip: str, n: int, outdir: Path) -> list[str]:
        """ffmpeg 等间隔抽 n 帧到 outdir, 返回帧路径列表; 缺 ffmpeg/失败 → []。"""
        dur = 0.0
        try:
            dur = float(probe_duration(clip)) or 0.0
        except Exception:  # noqa: BLE001
            dur = 0.0
        if dur <= 0:
            dur = 4.0  # 取不到时长时按默认镜长抽
        outdir.mkdir(parents=True, exist_ok=True)
        frames = []
        for i in range(max(1, n)):
            t = dur * (i + 0.5) / n
            dst = outdir / f"f{i:02d}.png"
            try:
                p = subprocess.run(
                    ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(clip),
                     "-frames:v", "1", "-q:v", "3", str(dst)],
                    capture_output=True, text=True, errors="replace")
                if dst.exists() and dst.stat().st_size > 0:
                    frames.append(str(dst))
            except FileNotFoundError:
                self.warn("找不到 ffmpeg(视频质检需要), 跳过抽帧。")
                return []
            except Exception:  # noqa: BLE001
                pass
        return frames

    def _merge_video(self, shot, seg_vis: list, n_segs: int, windowed: bool) -> dict:
        """把各滑窗的判分汇总成一条: 每个维度取【最差窗口】, 问题去重合并。"""
        base = {"shot_id": shot.shot_id, "character": (shot.characters[0] if shot.characters else "(空镜)"),
                "windows": n_segs, "windowed": bool(windowed)}
        vals = [v for v in seg_vis if isinstance(v, dict) and v]
        if not vals:
            base.update({"scores": {}, "overall": 0, "root_cause": "qc_failed",
                         "issues": ["视频质检无结果(限流/上传失败)"], "fix": "稍后重试或检查配额", "verdict": "review"})
            return base
        worst = lambda k: min(self._to5(v.get(k)) for v in vals)  # noqa: E731
        motion, physics, temporal, artifact = worst("motion"), worst("physics"), worst("temporal"), worst("artifact")
        overall = min(self._to5(v.get("overall"), default=min(motion, physics, temporal, artifact)) for v in vals)
        issues = []
        for v in vals:
            for it in (v.get("issues") or []):
                if it and it not in issues:
                    issues.append(it)
        fix = next((v.get("fix") for v in vals if v.get("fix")), "")
        if min(physics, temporal, artifact) <= 2 or overall <= 2:
            root, verdict = "video_broken", "review"
        elif overall >= 4:
            root, verdict = "ok", "good"
        else:
            root, verdict = "minor", "minor"
        raw = next((v.get("_raw") for v in vals if v.get("_raw")), "")
        base.update({
            "scores": {"motion": motion, "physics": physics, "temporal": temporal, "artifact": artifact},
            "overall": overall, "root_cause": root,
            "issues": issues, "fix": fix or "", "verdict": verdict,
            "raw": (raw or "")[:4000],   # GLM-4.6V 原始反馈(Web 展示用)
        })
        return base

    # ---- 视频路由 + 重写运动提示词 + 应用修复 ----
    @staticmethod
    def _route_video(rec: dict) -> str:
        """视频质检结论→动作: pass / reroll(随机时序崩坏→换 clip 种子) / reprompt(运动/调度错→重写运动词)。"""
        if rec.get("verdict") in ("good", "minor"):
            return "pass"
        # video_broken 多为时序/物理随机崩坏 → 换种子; 其它(动作没体现/近静止)→改运动提示词
        return "reroll" if rec.get("root_cause") == "video_broken" else "reprompt"

    _REWRITE_VID_SYS = (
        "你是短剧 I2V 运镜师, 按质检意见【重写一个镜头的视频运动提示词】, 修掉'动作没体现/画面近乎静止/"
        "运动不自然'等问题, 保持人物与场景不变(那些由起始关键帧决定)。只输出 JSON: {video_action_en, reason}。\n"
        "规则: video_action_en=明确、克制、可见的运动英文——给具体运镜(如 slow push in/pan left)或主体动作;"
        " 若原镜近乎静止(frozen), 加入明确的运动动词与镜头微动让它动起来; 不要引入新人物或让主体变形。")

    def rewrite_video(self, shot, rec: dict) -> dict:
        """GLM 重写 video_prompt_en(只动运动描述, 不动起始帧)。直接改 shot.video_prompt_en; 返回 JSON。"""
        if self.ctx.dry_run:
            data = {"video_action_en": "clear visible motion, slow push in", "reason": "dry"}
        else:
            payload = {"shot_id": shot.shot_id, "action_zh": shot.action,
                       "current_video_prompt": shot.video_prompt_en, "camera_motion": shot.camera_motion,
                       "qc": {"root_cause": rec.get("root_cause"), "issues": rec.get("issues"),
                              "fix": rec.get("fix")}}
            try:
                data = self.ctx.llm.chat_json(
                    TIER_STRUCTURE, self._qcp("12_rewrite_video.md", self._REWRITE_VID_SYS),
                    json.dumps(payload, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                self.warn(f"视频重写失败({shot.shot_id}), 保留原运动词: {e}")
                return {}
        if isinstance(data, dict) and (data.get("video_action_en") or "").strip():
            shot.video_prompt_en = build_video_prompt(shot.camera_motion, data["video_action_en"].strip())
            self._reapply_import_prompt_constraints(shot, "video")
        return data if isinstance(data, dict) else {}

    def apply_video_fixes(self, shot_list: ShotList, recs: list[dict],
                          max_retries: int = 2) -> tuple[list[str], list[str]]:
        """按视频质检结论改修并把待重出镜退回 keyframe_ok(让 VideoGenerator 重出 clip, 关键帧不动)。
        reroll→换 clip_seed; reprompt→重写运动词; 超 max_retries→needs_human(保留现 clip)。"""
        by_id = {s.shot_id: s for s in shot_list.shots}
        queued, needs_human = [], []
        for rec in recs:
            s = by_id.get(rec.get("shot_id"))
            if not s:
                continue
            route = self._route_video(rec)
            if route == "pass":
                continue
            if s.clip_retries >= max_retries:
                s.qc_notes = f"视频质检{max_retries}次仍不过(保留现clip): {rec.get('fix', '')}"[:300]
                needs_human.append(s.shot_id)
                continue
            s.status = "keyframe_ok"                 # 退回让 VideoGenerator 重出 clip
            if route == "reroll":
                parent_seed = int(s.clip_seed) or derive_legacy_seed(
                    "i2v",
                    s.shot_id,
                ).resolved_seed
                s.clip_seed = derive_reroll_seed(
                    parent_resolved_seed=parent_seed,
                    reroll_index=s.clip_retries + 1,
                ).resolved_seed
            else:
                self.rewrite_video(s, rec)
            s.qc_notes = (rec.get("fix") or "")[:300]
            s.clip_retries += 1
            queued.append(s.shot_id)
        shot_list.save(self.ctx.paths.shots / f"{shot_list.episode_id}_shot_list.json")
        if queued or needs_human:
            self.info(f"视频返工: 重出 {queued} needs_human={needs_human or '无'}")
        return queued, needs_human

    # ---- 整片【长程】质检(降画质整段上传 / 降级全片抽帧) ----
    _EP_SYS = (
        "你是AI短剧【整片长程】质检员, 必须挑刺、不许一律给5分。给你整集成片(或其均匀抽帧, 按时间先后)。"
        "从全局判断, 只输出JSON:\n"
        '{continuity:0-5, character_consistency:0-5, pacing:0-5, coherence:0-5, overall:0-5, issues:[中文短标签], fix:str}。\n'
        "continuity=镜头间衔接是否顺(有无突兀跳切/穿帮); "
        "character_consistency=同一人物【全片】是否一致(脸/发型/服装不跨镜突变); "
        "pacing=节奏(过快过慢/拖沓); coherence=叙事是否连贯看得懂。fix给一句中文怎么改。")

    def qc_episode(self, episode_id: str, final_path: str | None = None) -> dict:
        """整片长程质检: 成片降画质塞进上限后【整段上传】glm-5v-turbo(看全片时序);
        仍超限/上传失败 → 全片【均匀抽帧】上传(降级)。结果落 .cache/episode_qc.json。"""
        cache = self.ctx.paths.root / ".cache"
        cache.mkdir(parents=True, exist_ok=True)
        final = final_path or str(self.ctx.paths.output / episode_id / f"{episode_id}_final.mp4")
        if not os.path.exists(final):
            rec = {"episode": episode_id, "ok": False, "error": "成片不存在(还没合成)"}
            (cache / "episode_qc.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            return rec
        max_bytes = int(float(self.ctx.cfg("review", "video_max_mb", default=18)) * 1024 * 1024)
        work, method = final, "whole"
        if os.path.getsize(final) > max_bytes:
            ds = self._downscale_to_fit(final, cache / "_qc_ep" / f"{episode_id}_ds.mp4", max_bytes)
            if ds:
                work, method = ds, "downscaled"
        vis = None
        if self.ctx.dry_run:
            vis = {"continuity": 5, "character_consistency": 5, "pacing": 5,
                   "coherence": 5, "overall": 5, "issues": [], "fix": ""}
        else:
            if work and os.path.getsize(work) <= max_bytes:
                try:
                    vis = self.ctx.llm.vision_video_score(
                        self._qcp("10_qc_episode.md", self._EP_SYS),
                        f"整集 {episode_id} 成片, 做长程质检。", work)
                except Exception as e:  # noqa: BLE001
                    self.warn(f"整片视频上传质检失败, 回退抽帧: {e}")
                    vis = None
            if not vis:   # 仍超限 / 上传失败 → 全片均匀抽帧(长程覆盖)
                n = int(self.ctx.cfg("review", "episode_frames", default=24))
                frames = self._extract_frames(work or final, n, cache / "_qc_ep" / episode_id)
                if frames:
                    try:
                        vis = self.ctx.llm.vision_score(
                            self._qcp("10_qc_episode.md", self._EP_SYS),
                            f"整集 {episode_id} 成片均匀抽的 {len(frames)} 帧(时间先后), 做长程质检。", frames)
                        method = "frames"
                    except Exception as e:  # noqa: BLE001
                        self.warn(f"整片抽帧质检失败: {e}")
                        vis = {}
        vis = vis or {}
        cont, cc = self._to5(vis.get("continuity")), self._to5(vis.get("character_consistency"))
        pac, coh = self._to5(vis.get("pacing")), self._to5(vis.get("coherence"))
        overall = self._to5(vis.get("overall"), default=min(cont, cc, pac, coh))
        verdict = "review" if overall <= 2 else "good" if overall >= 4 else "minor"
        rec = {"episode": episode_id, "ok": True, "method": method,
               "scores": {"continuity": cont, "character_consistency": cc, "pacing": pac, "coherence": coh},
               "overall": overall, "issues": [i for i in (vis.get("issues") or []) if i],
               "fix": vis.get("fix", "") or "", "verdict": verdict}
        (cache / "episode_qc.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        self.info(f"整片长程质检完成({method}): overall={overall} verdict={verdict}")
        return rec

    # ---- 成片级审核 ----
    def review_episode(self, ep: Episode) -> Episode:
        issues = []
        target = self.ctx.cfg("output", "target_seconds", default=[60, 180])
        if not self.ctx.dry_run:
            if ep.duration_sec < target[0]:
                issues.append(f"时长偏短 {ep.duration_sec}s < {target[0]}s")
            if ep.duration_sec > target[1] * 1.2:
                issues.append(f"时长偏长 {ep.duration_sec}s")
        ep.qc_passed = len(issues) == 0
        ep.qc_report = "通过" if ep.qc_passed else "; ".join(issues)
        ep.save(self.ctx.paths.output / ep.episode_id / f"{ep.episode_id}_episode.json")
        self.info(f"成片审核: {ep.qc_report}")
        return ep
