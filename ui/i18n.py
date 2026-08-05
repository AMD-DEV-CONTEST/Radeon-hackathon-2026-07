"""i18n 国际化字典 — 中英双语."""
from __future__ import annotations

LANGS = ["中文", "English"]

STRINGS = {
    # 页头
    "title": {"zh": "FrameForge - AI 视频关键帧微调", "en": "FrameForge - AI Video Keyframe Editor"},
    "subtitle": {
        "zh": "AI 视频关键帧微调工坊 &mdash; 生成、选帧、选区、重绘、传播、导出",
        "en": "Generate, Select Frames, Choose Regions, Edit, Propagate & Export",
    },
    "lang_label": {"zh": "语言", "en": "Language"},

    # 状态栏
    "gpu_checking": {"zh": "GPU 检测中...", "en": "Detecting GPU..."},
    "comfy_checking": {"zh": "ComfyUI 检测中...", "en": "Checking ComfyUI..."},

    # Tab 1: 生成
    "tab_generate": {"zh": "1  生成视频", "en": "1  Generate"},
    "tab_generate_tip": {
        "zh": "输入提示词，点击「生成视频」。生成完成后自动跳到「编辑帧」Tab。",
        "en": "Enter a prompt and click \"Generate\". After generation, switch to the \"Edit\" tab.",
    },
    "prompt_label": {"zh": "提示词", "en": "Prompt"},
    "prompt_placeholder": {
        "zh": "一辆红色跑车在山间公路飞驰，电影感，高画质",
        "en": "A red sports car racing on a mountain road, cinematic, high quality",
    },
    "duration_label": {"zh": "时长（秒）", "en": "Duration (sec)"},
    "duration_info": {"zh": "1 秒约 16 帧", "en": "~16 frames per second"},
    "resolution_label": {"zh": "分辨率", "en": "Resolution"},
    "resolution_info": {"zh": "横屏 / 竖屏", "en": "Landscape / Portrait"},
    "backend_label": {"zh": "生成模型", "en": "Model"},
    "backend_info": {
        "zh": "Wan2.1: 轻量快速 | H3: 2K+原生音频(需ComfyUI v0.29.2+)",
        "en": "Wan2.1: Fast & lightweight | H3: Higher quality (requires ComfyUI v0.29.2+)",
    },
    "advanced_params": {"zh": "高级参数", "en": "Advanced Parameters"},
    "steps_label": {"zh": "采样步数", "en": "Sampling Steps"},
    "steps_info": {
        "zh": "步数越多越精细但越慢。H3 推荐 15-30，Wan2.1 推荐 20-40",
        "en": "More steps = finer quality but slower. H3: 15-30, Wan2.1: 20-40",
    },
    "seed_label": {"zh": "随机种子", "en": "Seed"},
    "seed_info": {"zh": "-1 = 随机", "en": "-1 = random"},
    "generate_btn": {"zh": "生成视频", "en": "Generate Video"},
    "ref_image_label": {"zh": "参考图（可选）", "en": "Reference Image (optional)"},
    "import_section": {"zh": "导入已有视频", "en": "Import Existing Video"},
    "import_video_label": {"zh": "拖入视频文件", "en": "Drop a video file here"},

    # Tab 2: 编辑
    "tab_edit": {"zh": "2  编辑帧", "en": "2  Edit Frames"},
    "tab_edit_tip": {
        "zh": "滑动「帧索引」选择关键帧 -> 在右侧区域标注图上点击要修改的区域 -> 输入编辑描述 -> 选择传播模式 -> 点击「应用编辑」。",
        "en": "Slide the frame index -> Click regions on the right -> Enter edit description -> Choose propagation mode -> Click \"Apply Edit\".",
    },
    "frame_preview_label": {"zh": "当前帧", "en": "Current Frame"},
    "frame_idx_label": {"zh": "帧索引", "en": "Frame Index"},
    "prev_btn": {"zh": "◀ 上一帧", "en": "◀ Prev"},
    "next_btn": {"zh": "下一帧 ▶", "en": "Next ▶"},
    "timeline_label": {"zh": "### 时间轴", "en": "### Timeline"},
    "region_canvas_label": {
        "zh": "区域标注图（点击选择要编辑的区域）",
        "en": "Region Map (click to select areas to edit)",
    },
    "region_info_default": {
        "zh": "<p class='tip-box'>请先选择帧</p>",
        "en": "<p class='tip-box'>Please select a frame first</p>",
    },
    "edit_prompt_label": {"zh": "编辑描述", "en": "Edit Description"},
    "edit_prompt_placeholder": {
        "zh": "把红色汽车改成蓝色跑车",
        "en": "Change the red car to a blue sports car",
    },
    "edit_params": {"zh": "编辑参数", "en": "Edit Parameters"},
    "denoise_label": {"zh": "重绘强度", "en": "Denoise Strength"},
    "denoise_info": {"zh": "越高改动越大", "en": "Higher = more change"},
    "controlnet_label": {"zh": "控制类型", "en": "Control Type"},
    "prop_settings": {"zh": "传播设置", "en": "Propagation Settings"},
    "prop_mode_label": {"zh": "传播模式", "en": "Propagation Mode"},
    "prop_mode_info": {
        "zh": "前向传播: 改一帧, 后续帧自动跟随",
        "en": "Forward: edit one frame, following frames auto-update",
    },
    "prop_range_label": {"zh": "传播范围（帧数）", "en": "Propagation Range (frames)"},
    "use_cn_label": {"zh": "启用 ControlNet", "en": "Enable ControlNet"},
    "apply_btn": {"zh": "应用编辑", "en": "Apply Edit"},
    "propagate_btn": {"zh": "仅传播", "en": "Propagate Only"},

    # Tab 3: 导出
    "tab_export": {"zh": "3  对比与导出", "en": "3  Compare & Export"},
    "tab_export_tip": {
        "zh": "对比修改前后的画面，确认后点击「导出视频」。",
        "en": "Compare before/after, then click \"Export Video\".",
    },
    "compare_btn": {"zh": "对比当前帧", "en": "Compare Current Frame"},
    "before_label": {"zh": "修改前", "en": "Before"},
    "after_label": {"zh": "修改后", "en": "After"},
    "keep_audio_label": {"zh": "保留原视频音轨", "en": "Keep original audio track"},
    "export_btn": {"zh": "导出视频", "en": "Export Video"},
    "output_video_label": {"zh": "最终视频", "en": "Final Video"},

    # 传播模式选项
    "prop_none": {"zh": "仅当前帧", "en": "Current Only"},
    "prop_forward": {"zh": "前向传播", "en": "Forward"},
    "prop_bidirectional": {"zh": "双向传播", "en": "Bidirectional"},
}


def t(key: str, lang: str = "中文") -> str:
    """获取翻译文本."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    lang_key = "zh" if lang == "中文" else "en"
    return entry.get(lang_key, entry.get("zh", key))


def prop_choices(lang: str = "中文"):
    """传播模式选项列表."""
    return [t("prop_none", lang), t("prop_forward", lang), t("prop_bidirectional", lang)]
