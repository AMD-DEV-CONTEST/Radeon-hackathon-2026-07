"""Gradio 组件定义与布局.

设计原则:
  - 三步流程清晰可见: 生成 -> 编辑 -> 导出
  - 渐进式披露: 核心参数可见, 高级参数折叠
  - 统一视觉语言: 自定义 Soft 主题 + CSS
  - 左右分栏: 编辑页左预览右画板
  - 中英双语切换
"""
from __future__ import annotations

import gradio as gr

from ui.i18n import LANGS, STRINGS, prop_choices, t


_THEME = gr.themes.Soft(
    primary_hue="emerald",
    secondary_hue="cyan",
    neutral_hue="slate",
    spacing_size=gr.themes.sizes.spacing_md,
    radius_size=gr.themes.sizes.radius_md,
    text_size=gr.themes.sizes.text_md,
    font=[gr.themes.GoogleFont("Noto Sans SC"), "ui-sans-serif", "system-ui", "sans-serif"],
)

_CSS = """
.gradio-container { max-width: 1280px !important; margin: 0 auto !important; }
footer { display: none !important; }

.app-header { text-align: center; padding: 16px 0 8px; border-bottom: 1px solid #334155; margin-bottom: 8px; position: relative; }
.app-header h1 { font-size: 1.6em; color: #10b981; margin: 0; }
.app-header p { color: #64748b; font-size: 0.85em; margin: 4px 0 0; }

.lang-switcher { position: absolute !important; top: 18px !important; right: 0 !important; min-width: 120px !important; }

.status-bar { display: flex; justify-content: center; gap: 12px; margin-bottom: 8px; }
.status-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 20px; font-size: 0.8em; font-weight: 500; }
.status-badge.ok { background: rgba(16,185,129,0.12); color: #10b981; border: 1px solid rgba(16,185,129,0.3); }
.status-badge.warn { background: rgba(245,158,11,0.12); color: #f59e0b; border: 1px solid rgba(245,158,11,0.3); }
.status-badge.err { background: rgba(239,68,68,0.12); color: #ef4444; border: 1px solid rgba(239,68,68,0.3); }

.tip-box { background: rgba(16,185,129,0.06); border-left: 3px solid #10b981; padding: 8px 14px; border-radius: 4px; margin: 6px 0; font-size: 0.85em; color: #94a3b8; }
.tab-label { font-size: 1.05em !important; font-weight: 600 !important; }
button.primary { font-weight: 600 !important; }
"""


def build_ui(handlers):
    lang = "中文"  # 默认中文

    with gr.Blocks(
        title=t("title", lang),
        analytics_enabled=False,
        css=_CSS,
    ) as demo:
        # ---- 页头（语言切换在 CSS 里定位到右上角）----
        header_html = gr.HTML(f"""
        <div class="app-header">
            <h1>FrameForge</h1>
            <p>{t("subtitle", lang)}</p>
        </div>
        """)
        lang_dd = gr.Dropdown(
            choices=LANGS, value=lang, label=t("lang_label", lang),
            elem_classes="lang-switcher", show_label=False, container=False,
        )

        state = gr.State(handlers.FrameForgeSession())
        lang_state = gr.State(lang)  # 当前语言状态

        # 状态栏
        with gr.Row(elem_classes="status-bar"):
            gpu_box = gr.Textbox(label="", interactive=False, value=t("gpu_checking", lang),
                                 elem_classes="status-badge", show_label=False, container=False, scale=1)
            comfy_box = gr.Textbox(label="", interactive=False, value=t("comfy_checking", lang),
                                   elem_classes="status-badge", show_label=False, container=False, scale=1)

        with gr.Tabs():
            # ==================== Tab 1: 生成 ====================
            with gr.Tab(t("tab_generate", lang), elem_classes="tab-label") as tab1:
                gen_tip = gr.HTML(f'<div class="tip-box">{t("tab_generate_tip", lang)}</div>')

                with gr.Row():
                    with gr.Column(scale=3):
                        prompt_in = gr.Textbox(
                            label=t("prompt_label", lang),
                            placeholder=t("prompt_placeholder", lang),
                            lines=3, max_lines=5,
                        )
                        with gr.Row():
                            duration_in = gr.Slider(1, 8, value=2, step=1, label=t("duration_label", lang),
                                                    info=t("duration_info", lang))
                            resolution_in = gr.Dropdown(
                                choices=["832x480", "1280x720", "480x832"],
                                value="832x480", label=t("resolution_label", lang),
                                info=t("resolution_info", lang),
                            )
                        with gr.Row():
                            backend_in = gr.Dropdown(
                                choices=["Wan2.1", "MiniMax H3"],
                                value="Wan2.1", label=t("backend_label", lang),
                                info=t("backend_info", lang),
                            )
                        with gr.Accordion(t("advanced_params", lang), open=True) as adv_acc:
                            steps_in = gr.Slider(5, 50, value=15, step=1,
                                                 label=t("steps_label", lang),
                                                 info=t("steps_info", lang))
                            seed_in = gr.Number(value=-1, label=t("seed_label", lang),
                                                info=t("seed_info", lang), precision=0)
                        generate_btn = gr.Button(t("generate_btn", lang), variant="primary", size="lg")

                    with gr.Column(scale=2):
                        ref_image_in = gr.Image(label=t("ref_image_label", lang), type="filepath", height=220)

                gr.Markdown("---")
                with gr.Accordion(t("import_section", lang), open=False) as import_acc:
                    import_video_in = gr.Video(label=t("import_video_label", lang), height=200)

                gen_status = gr.Markdown("", elem_classes="tip-box")

            # ==================== Tab 2: 编辑 ====================
            with gr.Tab(t("tab_edit", lang), elem_classes="tab-label") as tab2:
                edit_tip = gr.HTML(f'<div class="tip-box">{t("tab_edit_tip", lang)}</div>')

                with gr.Row():
                    # 左：帧预览 + 时间轴
                    with gr.Column(scale=1):
                        frame_preview = gr.Image(label=t("frame_preview_label", lang), interactive=False, height=500)
                        frame_idx_in = gr.Slider(1, 100, value=1, step=1, label=t("frame_idx_label", lang))
                        with gr.Row():
                            prev_btn = gr.Button(t("prev_btn", lang), size="sm")
                            next_btn = gr.Button(t("next_btn", lang), size="sm")
                        timeline_md = gr.Markdown(t("timeline_label", lang))
                        timeline_gallery = gr.Gallery(
                            label="", columns=6, height=180,
                            show_label=False, object_fit="cover", preview=False,
                        )

                    # 右：区域标注 + 编辑参数
                    with gr.Column(scale=1):
                        region_canvas = gr.Image(
                            label=t("region_canvas_label", lang),
                            interactive=True, height=500,
                        )
                        region_info = gr.HTML(value=t("region_info_default", lang))
                        edit_prompt_in = gr.Textbox(
                            label=t("edit_prompt_label", lang),
                            placeholder=t("edit_prompt_placeholder", lang),
                            lines=2,
                        )
                        with gr.Accordion(t("edit_params", lang), open=True) as edit_params_acc:
                            with gr.Row():
                                denoise_in = gr.Slider(0.0, 1.0, value=0.75, step=0.05,
                                                      label=t("denoise_label", lang), info=t("denoise_info", lang))
                                controlnet_in = gr.Dropdown(choices=["canny", "depth"],
                                                           value="canny", label=t("controlnet_label", lang))
                            edit_prop_acc = gr.Accordion(t("prop_settings", lang), open=True)
                            with edit_prop_acc:
                                prop_mode_in = gr.Radio(
                                    choices=prop_choices(lang),
                                    value=t("prop_bidirectional", lang), label=t("prop_mode_label", lang),
                                    info=t("prop_mode_info", lang),
                                )
                                prop_range_in = gr.Slider(1, 16, value=8, step=1,
                                                          label=t("prop_range_label", lang))
                                use_cn_in = gr.Checkbox(value=False, label=t("use_cn_label", lang))
                        with gr.Row():
                            apply_btn = gr.Button(t("apply_btn", lang), variant="primary", size="lg")
                            propagate_btn = gr.Button(t("propagate_btn", lang))

                edit_status = gr.Markdown("", elem_classes="tip-box")

            # ==================== Tab 3: 导出 ====================
            with gr.Tab(t("tab_export", lang), elem_classes="tab-label") as tab3:
                export_tip = gr.HTML(f'<div class="tip-box">{t("tab_export_tip", lang)}</div>')
                with gr.Row():
                    compare_btn = gr.Button(t("compare_btn", lang), size="sm")
                with gr.Row():
                    before_img = gr.Image(label=t("before_label", lang), interactive=False, height=280)
                    after_img = gr.Image(label=t("after_label", lang), interactive=False, height=280)
                gr.Markdown("---")
                with gr.Row():
                    keep_audio_in = gr.Checkbox(value=True, label=t("keep_audio_label", lang))
                    export_btn = gr.Button(t("export_btn", lang), variant="primary", size="lg")
                export_status = gr.Markdown("", elem_classes="tip-box")
                output_video = gr.Video(label=t("output_video_label", lang), height=320)

        # ==================== 语言切换 ====================
        def _switch_lang(lang_val):
            """切换语言后返回所有需要更新的组件值."""
            sub = t("subtitle", lang_val)
            return (
                f"""<div class="app-header"><h1>FrameForge</h1><p>{sub}</p></div>""",
                t("gpu_checking", lang_val),
                t("comfy_checking", lang_val),
                gr.Tab(label=t("tab_generate", lang_val)),
                f'<div class="tip-box">{t("tab_generate_tip", lang_val)}</div>',
                gr.Textbox(label=t("prompt_label", lang_val),
                           placeholder=t("prompt_placeholder", lang_val)),
                t("duration_label", lang_val),
                gr.Slider(label=t("duration_label", lang_val), info=t("duration_info", lang_val)),
                t("resolution_label", lang_val),
                gr.Dropdown(label=t("resolution_label", lang_val), info=t("resolution_info", lang_val)),
                t("backend_label", lang_val),
                gr.Dropdown(label=t("backend_label", lang_val), info=t("backend_info", lang_val)),
                gr.Accordion(label=t("advanced_params", lang_val)),
                gr.Slider(label=t("steps_label", lang_val), info=t("steps_info", lang_val)),
                gr.Slider(label=t("steps_label", lang_val)),
                gr.Number(label=t("seed_label", lang_val), info=t("seed_info", lang_val)),
                gr.Number(label=t("seed_label", lang_val)),
                gr.Button(t("generate_btn", lang_val), variant="primary"),
                gr.Image(label=t("ref_image_label", lang_val)),
                gr.Accordion(label=t("import_section", lang_val)),
                gr.Video(label=t("import_video_label", lang_val)),
                gr.Tab(label=t("tab_edit", lang_val)),
                f'<div class="tip-box">{t("tab_edit_tip", lang_val)}</div>',
                gr.Image(label=t("frame_preview_label", lang_val)),
                gr.Slider(label=t("frame_idx_label", lang_val)),
                gr.Button(t("prev_btn", lang_val)),
                gr.Button(t("next_btn", lang_val)),
                t("timeline_label", lang_val),
                gr.Image(label=t("region_canvas_label", lang_val)),
                t("region_info_default", lang_val),
                gr.Textbox(label=t("edit_prompt_label", lang_val),
                           placeholder=t("edit_prompt_placeholder", lang_val)),
                gr.Textbox(label=t("edit_prompt_label", lang_val)),
                gr.Accordion(label=t("edit_params", lang_val)),
                gr.Slider(label=t("denoise_label", lang_val), info=t("denoise_info", lang_val)),
                gr.Slider(label=t("denoise_label", lang_val)),
                gr.Dropdown(label=t("controlnet_label", lang_val)),
                gr.Accordion(label=t("prop_settings", lang_val)),
                gr.Radio(label=t("prop_mode_label", lang_val), info=t("prop_mode_info", lang_val)),
                gr.Radio(choices=prop_choices(lang_val), value=t("prop_bidirectional", lang_val)),
                gr.Slider(label=t("prop_range_label", lang_val)),
                gr.Checkbox(label=t("use_cn_label", lang_val)),
                gr.Button(t("apply_btn", lang_val), variant="primary"),
                gr.Button(t("propagate_btn", lang_val)),
                gr.Tab(label=t("tab_export", lang_val)),
                f'<div class="tip-box">{t("tab_export_tip", lang_val)}</div>',
                gr.Button(t("compare_btn", lang_val)),
                gr.Image(label=t("before_label", lang_val)),
                gr.Image(label=t("after_label", lang_val)),
                gr.Checkbox(label=t("keep_audio_label", lang_val)),
                gr.Button(t("export_btn", lang_val), variant="primary"),
                gr.Video(label=t("output_video_label", lang_val)),
                lang_val,
            )

        lang_outputs = [
            header_html,
            gpu_box,
            comfy_box,
            tab1,
            gen_tip,
            prompt_in,
            prompt_in,
            duration_in,
            duration_in,
            resolution_in,
            resolution_in,
            backend_in,
            backend_in,
            adv_acc,
            steps_in,
            steps_in,
            seed_in,
            seed_in,
            generate_btn,
            ref_image_in,
            import_acc,
            import_video_in,
            tab2,
            edit_tip,
            frame_preview,
            frame_idx_in,
            prev_btn,
            next_btn,
            timeline_md,
            region_canvas,
            region_info,
            edit_prompt_in,
            edit_prompt_in,
            edit_params_acc,
            denoise_in,
            denoise_in,
            controlnet_in,
            edit_prop_acc,
            prop_mode_in,
            prop_mode_in,
            prop_range_in,
            use_cn_in,
            apply_btn,
            propagate_btn,
            tab3,
            export_tip,
            compare_btn,
            before_img,
            after_img,
            keep_audio_in,
            export_btn,
            output_video,
            lang_state,
        ]

        lang_dd.change(_switch_lang, inputs=[lang_dd], outputs=lang_outputs)

        # ==================== 事件绑定 ====================
        demo.load(handlers.handler_gpu_status, outputs=gpu_box)
        demo.load(handlers.handler_comfyui_status, outputs=comfy_box)
        # 断线重连后自动恢复 UI
        demo.load(
            handlers.handle_restore_session,
            inputs=[state],
            outputs=[state, timeline_gallery, frame_idx_in, frame_preview, region_canvas, region_info],
        )

        # Tab 1: 生成
        _BACKEND_MAP = {"Wan2.1": "wan21", "MiniMax H3": "minimax_h3"}

        def _generate_wrapper(prompt, ref_img, duration, resolution, seed, backend_label, steps, st):
            backend = _BACKEND_MAP.get(backend_label, "wan21")
            result = handlers.handle_generate(prompt, ref_img, duration, resolution, seed, st, backend=backend, steps=int(steps))
            st, status, gallery, _, frame_preview = result
            handlers._sync_to_global(st)
            max_frames = max(2, st.frame_count)
            return (st, status, gallery,
                    gr.Slider(minimum=1, maximum=max_frames, value=1),
                    frame_preview, region_canvas, region_info)

        generate_btn.click(
            _generate_wrapper,
            inputs=[prompt_in, ref_image_in, duration_in, resolution_in, seed_in, backend_in, steps_in, state],
            outputs=[state, gen_status, timeline_gallery, frame_idx_in, frame_preview, region_canvas, region_info],
            api_name="handle_generate",
        )

        def _import_wrapper(video_file, st):
            result = handlers.handle_import_video(video_file, st)
            st, status, gallery, _, frame_preview = result
            handlers._sync_to_global(st)
            return (st, status, gallery,
                    gr.Slider(minimum=1, maximum=max(2, st.frame_count), value=1),
                    frame_preview, region_canvas, region_info)

        import_video_in.change(
            _import_wrapper,
            inputs=[import_video_in, state],
            outputs=[state, gen_status, timeline_gallery, frame_idx_in, frame_preview, region_canvas, region_info],
            api_name="handle_import_video",
        )

        # Tab 2: 帧选择
        frame_idx_in.release(
            handlers.handle_frame_select,
            inputs=[frame_idx_in, state],
            outputs=[state, edit_status, frame_preview, region_canvas, region_info],
        ).then(fn=lambda st: handlers._sync_to_global(st), inputs=[state])

        def _prev_frame(idx, st):
            new_idx = max(1, int(idx) - 1)
            result = handlers.handle_frame_select(new_idx, st)
            handlers._sync_to_global(result[0])
            return result

        prev_btn.click(
            _prev_frame,
            inputs=[frame_idx_in, state],
            outputs=[state, edit_status, frame_preview, region_canvas, region_info],
        ).then(lambda idx: max(1, int(idx) - 1), inputs=frame_idx_in, outputs=frame_idx_in)

        def _next_frame(idx, st):
            new_idx = int(idx) + 1
            result = handlers.handle_frame_select(new_idx, st)
            handlers._sync_to_global(result[0])
            return result

        next_btn.click(
            _next_frame,
            inputs=[frame_idx_in, state],
            outputs=[state, edit_status, frame_preview, region_canvas, region_info],
        ).then(lambda idx: int(idx) + 1, inputs=frame_idx_in, outputs=frame_idx_in)

        # 时间轴缩略图点击 -> 选中对应帧
        def _timeline_select(st, evt: gr.SelectData):
            idx = evt.index + 1  # gallery 从 0 开始, 帧从 1 开始
            result = handlers.handle_frame_select(idx, st)
            st2, status, frame_preview, region_canvas, region_info = result
            handlers._sync_to_global(st2)
            return st2, status, frame_preview, region_canvas, region_info, gr.Slider(value=idx)

        timeline_gallery.select(
            _timeline_select,
            inputs=[state],
            outputs=[state, edit_status, frame_preview, region_canvas, region_info, frame_idx_in],
        )

        # Tab 2: 编辑
        _PROP_MAP = {"none": "none", "forward": "forward", "bidirectional": "bidirectional"}

        def _apply_wrapper(edit_prompt, controlnet, denoise, use_cn, prop_range, prop_mode_label, st):
            # 映射当前语言的选择到模式
            _prop_modes = {t("prop_none"): "none", t("prop_forward"): "forward", t("prop_bidirectional"): "bidirectional"}
            prop_mode = _prop_modes.get(prop_mode_label, "bidirectional")
            auto_prop = prop_mode != "none"
            result = handlers.handle_apply_edit(edit_prompt, controlnet, denoise, use_cn, prop_range, auto_prop, prop_mode, st)
            handlers._sync_to_global(result[0])
            return result

        apply_btn.click(
            _apply_wrapper,
            inputs=[edit_prompt_in, controlnet_in, denoise_in,
                    use_cn_in, prop_range_in, prop_mode_in, state],
            outputs=[state, edit_status, after_img, before_img,
                     frame_preview, timeline_gallery],
        )
        region_canvas.select(
            handlers.handle_region_click,
            inputs=[state],
            outputs=[state, region_canvas, region_info],
        )
        propagate_btn.click(
            handlers.handle_propagate,
            inputs=[prop_range_in, state],
            outputs=[state, edit_status, timeline_gallery],
        ).then(fn=lambda st: handlers._sync_to_global(st), inputs=[state])

        # Tab 3: 对比 + 导出
        compare_btn.click(
            handlers.handle_compare,
            inputs=[frame_idx_in, state],
            outputs=[state, before_img, after_img],
        )
        export_btn.click(
            handlers.handle_export,
            inputs=[keep_audio_in, state],
            outputs=[state, export_status, output_video],
        ).then(fn=lambda st: handlers._sync_to_global(st), inputs=[state])

    return demo
