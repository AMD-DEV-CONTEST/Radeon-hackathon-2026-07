"""阶段 7 — 关键帧 agent(ComfyUI, 镜头级并行)。

为每个镜头先生成一张关键帧 PNG(而非直接 T2V), 用人物参考图做 IPAdapter/Kontext 注入,
保证镜头里的人=人物圣经里的人。关键帧是 I2V 的起始帧, “先图后视频”是一致性的关键策略。
单镜头任务由 orchestrator.run_shots_parallel 分发到两张卡。
"""
from __future__ import annotations

from pathlib import Path

from .base import Agent
from ..seeding import derive_legacy_seed
from ..schemas import Shot, CharacterBible


class KeyframeGenerator(Agent):
    name = "关键帧"

    def __init__(self, ctx, chars: CharacterBible, scenes=None):
        super().__init__(ctx)
        self.chars = chars
        self.scenes = scenes   # 用于无人物镜头的场景 img2img 锁场景(可选)
        self.core_only = bool(
            ctx.cfg("keyframe", "core_only", default=False)
        )
        self.model_name = ctx.cfg(
            "keyframe",
            "model_name",
            default="sdxl" if self.core_only else "qwen-image",
        )
        if self.core_only and self.model_name != "sdxl":
            raise RuntimeError("core-only 关键帧必须声明 sdxl 模型")
        # 三选一: 有人物→IPAdapter 锁脸; 无人物且开了场景锚→场景图 img2img; 否则普通文生图
        self.wf_plain = ctx.workflow_path(
            ctx.cfg("workflows", "keyframe", default="keyframe_flux_api.json"))
        self.wf_ref = ctx.workflow_path(
            ctx.cfg("workflows", "keyframe_ref", default="keyframe_sdxl_ipadapter_api.json"))
        self.wf_scene = ctx.workflow_path(
            ctx.cfg("workflows", "keyframe_scene_ref",
                    default="keyframe_scene_img2img_api.json"))
        # 可选: InstantID 强锁脸(有人物镜头, 远强于 IPAdapter; 需下 InstantID 模型)
        self.wf_instantid = ctx.workflow_path(
            ctx.cfg("workflows", "keyframe_instantid",
                    default="keyframe_instantid_api.json"))
        # ★默认人物方案★ Qwen-Image-Edit-2511 强编辑底模: 参考图保身份 + 强底模摆构图,
        #   替代 InstantID(不再外挂 ID 抢构图, 根治反物理)。需下 Qwen-Edit 模型。
        self.wf_qwen = ctx.workflow_path(
            ctx.cfg("workflows", "keyframe_qwen_edit",
                    default="keyframe_qwen_edit_api.json"))
        # ★无人物纯文生图★ Qwen-Image base 文生图(与 Edit 同家族, 统一画风), 替代 SDXL 文生图。
        #   需下 Qwen-Image base 底模(tools/download_models.py --base)。
        self.wf_qwen_t2i = ctx.workflow_path(
            ctx.cfg("workflows", "keyframe_qwen_t2i",
                    default="keyframe_qwen_t2i_api.json"))
        # ★关键帧 HQ★ keyframe.qwen_hq=true 时改走"去 Lightning + 高步数 + cfg>1"的 HQ 工作流,
        #   让 negative 生效(手/无文字/无人空镜更干净), 代价是慢约 5 倍。双锚/纯文生图各一份。
        self.qwen_hq = bool(ctx.cfg("keyframe", "qwen_hq", default=False))
        self.wf_qwen_hq = ctx.workflow_path(
            ctx.cfg("workflows", "keyframe_qwen_edit_hq",
                    default="keyframe_qwen_edit_hq_api.json"))
        self.wf_qwen_t2i_hq = ctx.workflow_path(
            ctx.cfg("workflows", "keyframe_qwen_t2i_hq",
                    default="keyframe_qwen_t2i_hq_api.json"))

    def __call__(self, shot: Shot, shard: int) -> None:
        comfy = self.ctx.comfy(
            shard,
            model_name=self.model_name,
            min_vram_mib=12000 if self.core_only else 16384,
        )
        out_dir = self.ctx.paths.keyframes / shot.episode_id
        # 人物锚 / 场景锚(force_t2i 时双锚清空 → 落到纯文生图分支)
        if self.core_only:
            ref_img, scene_ref = "", ""
        else:
            ref_img, scene_ref = self._resolve_anchors(shot)

        # 工作流选择(有人物): Qwen-Edit(强编辑底模, 默认) > InstantID > IPAdapter;
        #   无人物: 场景 img2img > 纯文生图。
        if self.core_only:
            use_qwen = use_iid = use_ref = use_scene = False
            use_qwen_t2i = hq_qwen = hq_t2i = False
            wf_path = self.wf_plain
            is_hq = False
        else:
            use_qwen = bool(ref_img) and self.wf_qwen.exists() \
                and self.ctx.cfg("keyframe", "use_qwen_edit", default=False)
            use_iid = bool(ref_img) and not use_qwen and self.wf_instantid.exists() \
                and self.ctx.cfg("keyframe", "use_instantid", default=False)
            use_ref = bool(ref_img) and not use_qwen and not use_iid \
                and self.wf_ref.exists()
            use_scene = bool(scene_ref) and self.wf_scene.exists()
            # 无参考图时优先 Qwen-Image base，否则回退 SDXL 文生图。
            use_qwen_t2i = (
                not use_qwen
                and not use_iid
                and not use_ref
                and not use_scene
                and self.wf_qwen_t2i.exists()
                and self.ctx.cfg(
                    "keyframe", "use_qwen_t2i", default=True
                )
            )
            hq_qwen = self.qwen_hq and self.wf_qwen_hq.exists()
            hq_t2i = self.qwen_hq and self.wf_qwen_t2i_hq.exists()
            wf_path = (
                (self.wf_qwen_hq if hq_qwen else self.wf_qwen)
                if use_qwen
                else self.wf_instantid
                if use_iid
                else self.wf_ref
                if use_ref
                else self.wf_scene
                if use_scene
                else (
                    self.wf_qwen_t2i_hq
                    if hq_t2i
                    else self.wf_qwen_t2i
                )
                if use_qwen_t2i
                else self.wf_plain
            )
            is_hq = (use_qwen and hq_qwen) or (
                use_qwen_t2i and hq_t2i
            )

        # 人物镜【双锚】: Qwen-Edit 在角色锚(image1)之外再喂场景锚(image2), 人物+场景双一致。
        #   该场景无锚图(scene_bible.ref_images 为空)时 scene_ref2="" → 运行前自动剥除 image2,
        #   退回单锚, 不报错。开关 keyframe.qwen_scene_ref(默认 true)。
        scene_ref2 = ""
        if use_qwen and self._eff_anchor_mode(shot) == "dual":
            scene_ref2 = self._scene_anchor(shot)

        params = {
            "POS_PROMPT": shot.visual_prompt_en,
            "NEG_PROMPT": shot.negative_prompt,
            "REF_IMAGE": Path(ref_img).name if ref_img else "",
            "REF_IMAGE2": Path(scene_ref2).name if scene_ref2 else "",  # Qwen-Edit 场景锚(image2)
            "CONTROL_IMAGE": Path(scene_ref).name if scene_ref else "",  # 场景 img2img 用
            "SEED": self._seed_for(shot),
            "WIDTH": self.ctx.cfg("image", "width", default=768),
            "HEIGHT": self.ctx.cfg("image", "height", default=1344),
            # 风格锚: 可换写实/动漫专精 SDXL 底模, 一处改全片统一画风。
            "CKPT": self.ctx.cfg("keyframe", "checkpoint",
                                 default="sd_xl_base_1.0.safetensors"),
            "DENOISE": float(self.ctx.cfg("keyframe", "scene_ref_denoise", default=0.6)),
            # IPAdapter 调参: weight 适度降低 + end_at 提前(只前段锁脸, 后段交还基模出画风),
            # 避免参考图把画风也一起带歪。仅 keyframe_ref 工作流含这两个占位符, 其它会忽略。
            "IP_WEIGHT": float(self.ctx.cfg("keyframe", "ip_weight", default=0.7)),
            "IP_END": float(self.ctx.cfg("keyframe", "ip_end", default=0.6)),
            "INSTANTID_WEIGHT": float(self.ctx.cfg("keyframe", "instantid_weight", default=0.8)),
            # InstantID Advanced 解耦旋钮: noise=0 关掉人脸 embedding 随机化(防漂移/老化),
            # cn_strength 是 kps 几何约束, start/end 是锁脸去噪覆盖区间。仅 InstantID 工作流含这些占位符。
            "INSTANTID_CN": float(self.ctx.cfg("keyframe", "instantid_cn_strength", default=0.7)),
            "INSTANTID_NOISE": float(self.ctx.cfg("keyframe", "instantid_noise", default=0.0)),
            "INSTANTID_START": float(self.ctx.cfg("keyframe", "instantid_start", default=0.0)),
            "INSTANTID_END": float(self.ctx.cfg("keyframe", "instantid_end", default=1.0)),
            # Qwen-Image-Edit 旋钮(仅 keyframe_qwen_edit 工作流含这些占位符)。4 步 Lightning 默认。
            "QWEN_CKPT": self.ctx.cfg("keyframe", "qwen_checkpoint",
                                      default="qwen_image_edit_2511_fp8mixed.safetensors"),
            # Qwen-Image base 纯文生图底模(仅 keyframe_qwen_t2i 工作流用)。
            "QWEN_T2I_CKPT": self.ctx.cfg("keyframe", "qwen_t2i_checkpoint",
                                          default="qwen_image_fp8_e4m3fn.safetensors"),
            # HQ 镜用高步数/cfg(负向生效); 否则 4 步 Lightning cfg1。
            "QWEN_STEPS": int(self.ctx.cfg("keyframe", "qwen_hq_steps", default=20)) if is_hq
            else int(self.ctx.cfg("keyframe", "qwen_steps", default=4)),
            "QWEN_CFG": float(self.ctx.cfg("keyframe", "qwen_hq_cfg", default=3.0)) if is_hq
            else float(self.ctx.cfg("keyframe", "qwen_cfg", default=1.0)),
        }
        if not self.ctx.dry_run:
            if use_qwen or use_iid or use_ref:
                comfy.upload_image(ref_img)     # 人物参考图 → Qwen-Edit / InstantID / IPAdapter
                if use_qwen and scene_ref2:
                    comfy.upload_image(scene_ref2)  # 场景锚图 → Qwen-Edit image2(双一致)
            elif use_scene:
                comfy.upload_image(scene_ref)   # 场景参考图 → img2img 起始帧

        if not wf_path.is_file():
            raise RuntimeError(f"关键帧工作流不存在: {wf_path}")
        wf = comfy.load_workflow(wf_path)
        if not isinstance(wf, dict) or not any(
            isinstance(node, dict) and node.get("class_type") == "SaveImage"
            for node in wf.values()
        ):
            raise RuntimeError(f"关键帧工作流没有 SaveImage 输出: {wf_path}")
        wf = comfy.inject(wf, params)
        # 人物镜无场景锚时, 剥除 Qwen-Edit 的 image2(及其空 LoadImage), 退回单锚, 避免空图报错。
        if use_qwen and not scene_ref2:
            wf = self._strip_empty_loadimage(wf)
        # 可选风格 LoRA: 配了才在 checkpoint 后插一层 LoraLoader(默认不挂, 零改动)。
        lora = self.ctx.cfg("keyframe", "style_lora", default="")
        if lora and not self.core_only:
            wf = self._apply_style_lora(
                wf, lora,
                float(self.ctx.cfg("keyframe", "style_lora_strength", default=0.8)))
        self.ctx.progress.start_shot(shot.shot_id, "keyframe", shard, comfy.base,
                                     episode=shot.episode_id)
        try:
            paths = comfy.run(
                wf, out_dir, prefix=shot.shot_id,
                progress_cb=lambda v, m, node: self.ctx.progress.update_step(
                    shot.shot_id, node, v, m))
        finally:
            self.ctx.progress.finish_shot(shot.shot_id)
        if paths:
            shot.keyframe_path = str(paths[0])
            shot.status = "keyframe_ok"
        else:
            raise RuntimeError("关键帧无产物")

    def _eff_anchor_mode(self, shot: Shot) -> str:
        """解析本镜【有效锚点策略】: dual/char/scene/none。
        · force_t2i 或 anchor_mode=='none' → none(纯文生图)。
        · anchor_mode 显式给了 dual/char/scene → 直接用(分镜阶段声明, 见 [[anchor_mode]])。
        · 留空 → 按 characters + 配置【自动推断】, 与历史行为完全一致(向后兼容):
            有主角且有锚图 → dual(若开 qwen_scene_ref)否则 char;
            否则(空镜/无锚角色) → scene(若开 use_scene_ref 且该场景有锚图)否则 none。"""
        if bool(getattr(shot, "force_t2i", False)):
            return "none"
        m = (getattr(shot, "anchor_mode", "") or "").strip().lower()
        if m in ("dual", "char", "scene", "none"):
            return m
        # 自动推断(legacy)
        has_char_ref = False
        if shot.characters:
            c = self.chars.get(shot.characters[0])
            has_char_ref = bool(c and c.ref_images)
        if has_char_ref:
            return "dual" if self.ctx.cfg("keyframe", "qwen_scene_ref", default=True) else "char"
        return "scene" if self._scene_ref(shot) else "none"

    def _resolve_anchors(self, shot: Shot) -> tuple[str, str]:
        """解析(人物锚 image1, 场景图生图锚)路径, 由 _eff_anchor_mode 决定。
        (双锚的场景 image2 单独在 __call__ 里按 mode=='dual' 处理。)"""
        mode = self._eff_anchor_mode(shot)
        if mode == "none":
            return "", ""
        ref_img = ""
        if mode in ("dual", "char") and shot.characters:
            c = self.chars.get(shot.characters[0])
            if c and c.ref_images:
                ref_img = c.ref_images[0]
        scene_ref = self._scene_anchor(shot) if mode == "scene" else ""
        return ref_img, scene_ref

    def _seed_for(self, shot: Shot) -> int:
        """种子策略(跨镜头一致性)：有人物→复用该角色的 seed(同角色所有镜头同种子,
        稳住潜空间起点)；无人物→按场景(其次本集)取稳定种子,让同一场景空镜风格一致。
        比原先 hash(shot_id) 每镜乱跳更有利于人物/风格稳定。"""
        if int(getattr(shot, "keyframe_seed", 0)):      # 单镜重 roll 覆盖(质检返工用)
            return int(shot.keyframe_seed) & 0x7FFFFFFF
        if shot.characters:
            c = self.chars.get(shot.characters[0])
            if c and int(getattr(c, "seed", 0)):
                return int(c.seed) & 0x7FFFFFFF
        base = shot.scene_id or shot.episode_id or shot.shot_id
        return derive_legacy_seed("keyframe", base).resolved_seed

    # 镜头取景 → 多角度场景锚标签(中文动作/提示词关键词命中即选该角度; 都不命中→driver 默认)。
    _ANGLE_KEYWORDS = (
        ("rearview", ("后视镜", "rearview", "rear view mirror")),
        ("backseat", ("后座", "后排", "乘客", "情侣", "副驾", "back seat", "passenger")),
        ("side", ("车窗", "靠窗", "侧脸", "side window")),
        ("exterior", ("车外", "车旁", "下车", "车门", "站在车", "outside the car", "exterior")),
        ("driver", ("方向盘", "驾驶", "司机", "steering wheel", "driver")),
    )

    def _scene_anchor(self, shot: Shot) -> str:
        """该镜场景的基准锚图路径。多角度内景(scene.angle_refs 非空, 如车内): 按本镜取景挑角度
        (后视镜/后座/侧窗/车外/驾驶位); 否则用单张 ref_images[0]。供双锚 image2 与空镜 img2img 共用。"""
        if not self.scenes or not shot.scene_id:
            return ""
        s = self.scenes.get(shot.scene_id)
        if not s:
            return ""
        angles = dict(getattr(s, "angle_refs", None) or {})
        if angles:
            text = (shot.action or "") + " " + (shot.visual_prompt_en or "")
            label = "driver"                       # 默认驾驶位视角
            for lab, kws in self._ANGLE_KEYWORDS:
                if any(k in text for k in kws):
                    label = lab
                    break
            return angles.get(label) or (s.ref_images[0] if s.ref_images
                                         else next(iter(angles.values()), ""))
        return s.ref_images[0] if s.ref_images else ""

    def _scene_ref(self, shot: Shot) -> str:
        """无人物镜头: 开启 keyframe.use_scene_ref 且该场景有参考图时, 返回其路径,
        用于从场景图 img2img 锁住背景构图/色调(免额外模型)。默认关。"""
        if not self.ctx.cfg("keyframe", "use_scene_ref", default=False):
            return ""
        return self._scene_anchor(shot)

    @staticmethod
    def _strip_empty_loadimage(wf: dict) -> dict:
        """删除 image 占位被注入成空串的 LoadImage 节点, 并移除所有指向它的输入边
        (如 TextEncodeQwenImageEditPlus 的 image2)。用于人物镜无场景锚时退回单锚。"""
        empties = {nid for nid, n in wf.items()
                   if isinstance(n, dict) and n.get("class_type") == "LoadImage"
                   and not str((n.get("inputs") or {}).get("image", "")).strip()}
        for nid in empties:
            wf.pop(nid, None)
        for n in wf.values():
            if not isinstance(n, dict):
                continue
            ins = n.get("inputs") or {}
            for k in [k for k, v in ins.items()
                      if isinstance(v, list) and len(v) == 2 and v[0] in empties]:
                ins.pop(k, None)
        return wf

    @staticmethod
    def _apply_style_lora(wf: dict, lora_name: str, strength: float) -> dict:
        """在 CheckpointLoaderSimple 之后插入一层 LoraLoader, 把所有原本引用 checkpoint
        的 model([id,0])/clip([id,1]) 下游输入改接到 LoRA(VAE [id,2] 不变)。这样无需为
        每个工作流单独维护一份"带 LoRA"的版本。无 lora_name 时原样返回(零改动)。"""
        if not lora_name:
            return wf
        ckpt_id = next((nid for nid, n in wf.items()
                        if isinstance(n, dict)
                        and n.get("class_type") == "CheckpointLoaderSimple"), None)
        if ckpt_id is None or "lora_style" in wf:
            return wf
        lid = "lora_style"
        for n in wf.values():
            if not isinstance(n, dict):
                continue
            for k, v in (n.get("inputs") or {}).items():
                if isinstance(v, list) and len(v) == 2 and v[0] == ckpt_id and v[1] in (0, 1):
                    n["inputs"][k] = [lid, v[1]]
        wf[lid] = {"class_type": "LoraLoader",
                   "inputs": {"lora_name": lora_name,
                              "strength_model": strength, "strength_clip": strength,
                              "model": [ckpt_id, 0], "clip": [ckpt_id, 1]}}
        return wf
