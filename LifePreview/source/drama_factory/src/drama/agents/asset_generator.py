"""阶段 5/6 — 人物/场景资产 agent。

默认走【本地 Qwen-Image base 文生图】(assets.char_backend / scene_backend = qwen_local),
按"设定集"版式为每个角色出一整套资产、为每个场景出干净背景图：
  · front       正脸锚(给关键帧 Qwen-Edit 当 image1, = ref_images[0])
  · turnaround  三视图(正/侧/后 一行, 同一角色一致设计)
  · expressions 表情集(同一张脸的 9 格情绪网格)
  · costume     服装全身图(有 outfit_default 时)
  · scene       干净空镜 establishing 背景图(无人物)
本地失败按张回退云端 CogView, 不阻断。提示词按"角色设定表"设计: 只取 visual_style 的画风部分
(丢掉霓虹/车窗等场景元素, 否则污染本应干净的设定表), 强制 plain 背景 + no environment + 专用负向。
"""
from __future__ import annotations

from pathlib import Path
import stat

from .base import Agent
from ..seeding import derive_legacy_seed
from ..schemas import CharacterBible, SceneBible


class AssetGenerator(Agent):
    name = "资产生成"

    # qwen_local 时这些 view 全走本地 Qwen base(失败按张回退 CogView)。
    QWEN_VIEWS = {"front", "turnaround", "expressions", "costume"}

    # 角色设定表共用负向: 压掉"环境/场景/多余人物/文字标签", 保证是干净的角色参考表(非剧照)。
    SHEET_NEG = ("background scenery, environment, room interior, street, car interior, neon, "
                 "cluttered background, props, multiple different people, duplicated different face, "
                 "inconsistent design, text, label, caption, watermark, signature, "
                 "lowres, blurry, bad anatomy, bad hands, extra fingers, deformed, disfigured")
    # 场景图负向: 压掉人物(含小贩/店主/剪影等强人物先验场所易漏的)。
    SCENE_NEG = ("people, person, man, woman, character, human figure, crowd, portrait, "
                 "vendor, shopkeeper, cook, pedestrian, silhouette of a person, "
                 "text, watermark, signature, lowres, blurry, deformed")

    # 表情集情绪(9 格, 短剧常用)。想改情绪就改这里。
    EXPRESSIONS = ("calm, gentle smile, laughing, angry, sad, surprised, "
                   "exhausted, anxious, relieved")

    def _portrait(self) -> str:
        """竖屏关键帧尺寸(front/costume/scene 用; 与 9:16 关键帧一致)。"""
        return (f"{int(self.ctx.cfg('image', 'width', default=768))}x"
                f"{int(self.ctx.cfg('image', 'height', default=1344))}")

    @staticmethod
    def _art_style(visual_style: str) -> str:
        """只取全局 visual_style 的【画风】前两段(如 'cinematic realism, gritty urban texture'),
        丢掉'neon / wet windshield'等场景元素——否则会污染本应干净的角色设定表/场景establishing。"""
        vs = (visual_style or "").strip().strip(",")
        if not vs:
            return ""
        clauses = [c.strip() for c in vs.split(",") if c.strip()]
        return ", ".join(clauses[:2])

    @staticmethod
    def _valid_local_image(path_value: object) -> bool:
        """Return true only for a readable, regular, non-linked PNG/JPEG file."""
        if not isinstance(path_value, str) or not path_value.strip():
            return False
        path = Path(path_value)
        try:
            info = path.lstat()
            reparse = getattr(info, "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
            )
            if path.is_symlink() or reparse or not stat.S_ISREG(info.st_mode):
                return False
            with path.open("rb") as handle:
                header = handle.read(8)
        except (OSError, ValueError):
            return False
        return header.startswith(b"\x89PNG\r\n\x1a\n") or header.startswith(
            b"\xff\xd8\xff"
        )

    @classmethod
    def _can_preserve(cls, ref_images: object) -> bool:
        return (
            isinstance(ref_images, list)
            and bool(ref_images)
            and all(cls._valid_local_image(path) for path in ref_images)
        )

    def run_characters(self, chars: CharacterBible, visual_style: str = "",
                       save: bool = True, only=None,
                       preserve_existing: bool = False) -> CharacterBible:
        """only=None 生成全部; only=可迭代 char_id 集 → 只生成这些(其余保留已有 ref_images 不动)。
        用于①公共资产全书一次(only=公共角色) ②逐集只补/只改本集私有资产(权限分层, 不碰公共)。"""
        ap = (self._art_style(visual_style) + ", ") if self._art_style(visual_style) else ""
        backend = self.ctx.cfg("assets", "char_backend", default="qwen_local")
        portrait, wide, grid = self._portrait(), "1536x768", "1152x1152"
        only = set(only) if only is not None else None
        for c in chars.characters:
            if only is not None and c.char_id not in only:
                continue
            if preserve_existing and self._can_preserve(c.ref_images):
                self.info(f"角色 {c.name}: 保留 {len(c.ref_images)} 张导入参考图")
                continue
            out_dir = self.ctx.paths.assets_chars / c.char_id
            refs = []
            seed = int(getattr(c, "seed", 0)) or derive_legacy_seed(
                "character-asset",
                c.char_id,
            ).resolved_seed
            lock = c.prompt_lock_en
            # 一套"设定集"(参照角色设定表/三视图/表情集版式)。front 必为 ref_images[0]。
            sheets = [
                ("front", portrait,
                 f"{ap}{lock}, single character, front-facing head and shoulders portrait, "
                 f"neutral expression, looking straight at camera, even soft studio lighting, "
                 f"plain seamless light grey background, isolated character, no environment, "
                 f"sharp focus, high detail"),
                ("turnaround", wide,
                 f"{ap}{lock}, character turnaround model sheet, one identical character shown in "
                 f"three full-body views in one horizontal row: front view, side profile view, back view, "
                 f"identical design outfit hairstyle and proportions across all three views, neutral A-pose "
                 f"with arms slightly away from body, even flat lighting, plain white background, "
                 f"orthographic character reference sheet, isolated character, no environment"),
                ("expressions", grid,
                 f"{ap}{lock}, character expression sheet, a neat 3x3 grid of one identical character's "
                 f"head and shoulders showing nine facial emotions ({self.EXPRESSIONS}), "
                 f"the same face hairstyle and outfit in every cell, evenly spaced grid, "
                 f"consistent character design, plain white background, no environment"),
            ]
            if self.ctx.cfg("assets", "costume_ref", default=True) and c.outfit_default:
                sheets.append((
                    "costume", portrait,
                    f"{ap}{lock}, full-body costume reference, the character standing straight facing "
                    f"camera, full outfit clearly visible: {c.outfit_default}, neutral pose, even lighting, "
                    f"plain light grey background, isolated character, no environment, high detail"))
            for view, sz, prompt in sheets:
                dst = out_dir / view / f"{c.char_id}_{view}.png"
                p = None
                if backend == "qwen_local" and view in self.QWEN_VIEWS:
                    try:
                        p = self._qwen_asset(prompt, dst, seed, sz, neg=self.SHEET_NEG)
                    except Exception as e:  # noqa: BLE001 本地失败回退云端, 不阻断
                        self.warn(f"角色 {c.name} {view} 本地 Qwen 失败, 回退 CogView: {e}")
                        p = None
                if p is None:
                    try:
                        p = self.ctx.llm.generate_image(prompt, dst, size=sz, seed=seed)
                    except Exception as e:  # noqa: BLE001 单张失败不阻断其它
                        self.warn(f"角色 {c.name} {view} 生成失败: {e}")
                        p = None
                if p is not None:
                    refs.append(str(p))
            c.ref_images = refs
            c.model_version = "qwen-image-base" if backend == "qwen_local" else "cogview-4"
            self.info(f"角色 {c.name}: {len(refs)} 张设定图(正脸+三视图+表情"
                      f"{'+服装' if len(refs) > 3 else ''}, 后端={backend})")
        if save:
            chars.save(self.ctx.paths.bible / "character_bible.json")
        return chars

    def _qwen_asset(self, prompt: str, dst: Path, seed: int, size_str: str,
                    neg: str | None = None) -> Path:
        """本地 ComfyUI Qwen-Image base 文生图, 出一张资产图。
        ★默认走【HQ 资产模式】(assets.qwen_hq=true): keyframe_qwen_t2i_hq 工作流(去 Lightning, ~20步,
        cfg≈3) → 负向真正生效(干净空场景/无文字/手更好)。关闭则回退 4 步 Lightning 的 keyframe_qwen_t2i。
        neg 传该资产专用负向。失败抛异常由调用方回退 CogView。"""
        comfy = self.ctx.comfy(
            0, model_name="qwen-image", min_vram_mib=16384
        )
        hq = bool(self.ctx.cfg("assets", "qwen_hq", default=True))
        if hq:
            wf_name = self.ctx.cfg("workflows", "keyframe_qwen_t2i_hq",
                                   default="keyframe_qwen_t2i_hq_api.json")
            steps = int(self.ctx.cfg("assets", "qwen_steps", default=20))
            cfg = float(self.ctx.cfg("assets", "qwen_cfg", default=3.0))
        else:
            wf_name = self.ctx.cfg("workflows", "keyframe_qwen_t2i",
                                   default="keyframe_qwen_t2i_api.json")
            steps = int(self.ctx.cfg("keyframe", "qwen_steps", default=4))
            cfg = float(self.ctx.cfg("keyframe", "qwen_cfg", default=1.0))
        wf_path = self.ctx.workflow_path(wf_name)
        if not wf_path.exists():
            raise RuntimeError(f"缺工作流 {wf_path.name}")
        try:
            w, h = (int(x) for x in str(size_str).lower().split("x"))
        except Exception:  # noqa: BLE001
            w = int(self.ctx.cfg("image", "width", default=768))
            h = int(self.ctx.cfg("image", "height", default=1344))
        params = {
            "POS_PROMPT": prompt,
            "NEG_PROMPT": neg or self.ctx.cfg(
                "keyframe", "qwen_t2i_neg",
                default="lowres, blurry, bad anatomy, bad hands, extra fingers, "
                        "deformed, disfigured, text, watermark, signature"),
            "SEED": int(seed) & 0x7FFFFFFF, "WIDTH": w, "HEIGHT": h,
            "QWEN_T2I_CKPT": self.ctx.cfg("keyframe", "qwen_t2i_checkpoint",
                                          default="qwen_image_fp8_e4m3fn.safetensors"),
            "QWEN_STEPS": steps, "QWEN_CFG": cfg,
        }
        wf = comfy.inject(comfy.load_workflow(wf_path), params)
        paths = comfy.run(wf, dst.parent, prefix=dst.stem)
        if not paths:
            raise RuntimeError("Qwen 资产无产物")
        return paths[0]

    def _multi_angle_set(self, scene) -> dict:
        """该场景是否需要【多角度锚】: scene_id/name 命中 assets.multi_angle_keywords(如 car/车) →
        返回 assets.scene_angles(角度标签->英文取景描述); 否则空。默认空(不开多角度=旧单锚行为)。"""
        kws = self.ctx.cfg("assets", "multi_angle_keywords", default=[]) or []
        if not kws:
            return {}
        hay = (scene.scene_id + " " + (getattr(scene, "name", "") or "")).lower()
        if not any(str(k).lower() in hay for k in kws):
            return {}
        return dict(self.ctx.cfg("assets", "scene_angles", default={}) or {})

    def run_scenes(self, scenes: SceneBible, visual_style: str = "", save: bool = True,
                   only=None, preserve_existing: bool = False) -> SceneBible:
        """only=None 全部; only=可迭代 scene_id 集 → 只生成这些(公共一次 / 逐集补私有场景)。"""
        ap = (self._art_style(visual_style) + ", ") if self._art_style(visual_style) else ""
        backend = self.ctx.cfg("assets", "scene_backend", default="qwen_local")
        size = self._portrait()    # 竖屏(与 9:16 关键帧一致, 作 Qwen-Edit 的 image2 场景锚)
        only = set(only) if only is not None else None
        for s in scenes.scenes:
            if only is not None and s.scene_id not in only:
                continue
            if preserve_existing and self._can_preserve(s.ref_images):
                self.info(f"场景 {s.name}: 保留 {len(s.ref_images)} 张导入参考图")
                continue
            dst = self.ctx.paths.assets_scenes / s.scene_id / f"{s.scene_id}.png"
            seed = int(getattr(s, "seed", 0)) or derive_legacy_seed(
                "scene-asset",
                s.scene_id,
            ).resolved_seed
            # 先把"空无一人/打烊"作为主体放最前(正向最强), 再接地点; 否则强人物先验的场所(食摊等)会冒人。
            prompt = (f"{ap}an empty deserted unoccupied location with absolutely no people, "
                      f"nobody around, closed and quiet, abandoned at this hour, "
                      f"{s.prompt_lock_en}, clean wide establishing shot of the empty environment, "
                      f"no person, cinematic background art, high detail")
            p = None
            if backend == "qwen_local":
                try:
                    p = self._qwen_asset(prompt, dst, seed, size, neg=self.SCENE_NEG)
                except Exception as e:  # noqa: BLE001
                    self.warn(f"场景 {s.name} 本地 Qwen 失败, 回退 CogView: {e}")
                    p = None
            if p is None:
                try:
                    p = self.ctx.llm.generate_image(prompt, dst, size=size, seed=seed)
                except Exception as e:  # noqa: BLE001
                    self.warn(f"场景 {s.name} 生成失败: {e}")
                    p = None
            if p is not None:
                s.ref_images = [str(p)]
            # 多角度内景(车内等反复出现的场景): 再各出一张不同取景的【空场景锚】, 供关键帧按镜头选角度。
            angle_set = self._multi_angle_set(s)
            if angle_set:
                s.angle_refs = {}
                for label, spec in angle_set.items():
                    # spec 支持两种: 字符串(仅取景) 或 {pos, neg}(取景 + 该角度硬负向)。
                    pos = spec.get("pos", "") if isinstance(spec, dict) else str(spec)
                    aneg = spec.get("neg", "") if isinstance(spec, dict) else ""
                    # 角度 pos 自带车型/夜景/取景, 不再注入 prompt_lock_en(对 exterior 会打架)。
                    aprompt = (f"{ap}{pos}, an empty unoccupied scene with absolutely no people, nobody, "
                               f"cinematic background art, high detail")
                    neg_full = self.SCENE_NEG + (", " + aneg if aneg else "")
                    adst = self.ctx.paths.assets_scenes / s.scene_id / f"{s.scene_id}_{label}.png"
                    label_offset = derive_legacy_seed(
                        "asset-view",
                        label,
                    ).resolved_seed & 0xFFFF
                    aseed = (seed + label_offset) & 0x7FFFFFFF
                    ap_path = None
                    if backend == "qwen_local":
                        try:
                            ap_path = self._qwen_asset(aprompt, adst, aseed, size, neg=neg_full)
                        except Exception as e:  # noqa: BLE001
                            self.warn(f"场景 {s.name} 角度 {label} 本地失败, 回退: {e}"); ap_path = None
                    if ap_path is None:
                        try:
                            ap_path = self.ctx.llm.generate_image(aprompt, adst, size=size, seed=aseed)
                        except Exception as e:  # noqa: BLE001
                            self.warn(f"场景 {s.name} 角度 {label} 生成失败: {e}"); ap_path = None
                    if ap_path is not None:
                        s.angle_refs[label] = str(ap_path)
                if s.angle_refs:
                    self.info(f"场景 {s.name}: +{len(s.angle_refs)} 个角度锚 {list(s.angle_refs)}")
            self.info(f"场景 {s.name}: {len(s.ref_images)} 张场景图(后端={backend})")
        if save:
            scenes.save(self.ctx.paths.bible / "scene_bible.json")
        return scenes
