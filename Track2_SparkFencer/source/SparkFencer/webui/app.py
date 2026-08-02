"""SparkFencer WebUI — 视频分析 / 教练问答 / 场次浏览(全本地)。

Run on the GPU host, access via SSH port forward:
  ssh -L 7860:localhost:7860 <host> 'cd ~/work/SparkFencer && .venv/bin/python webui/app.py'
"""

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import gradio as gr
import numpy as np

from webui.pipeline import (
    list_sessions_info, load_session_assets, read_first_frame, run_webui_analysis,
)

CORNER_LABELS = {
    "zh": ["远端左角 ①", "远端右角 ②", "近端右角 ③", "近端左角 ④"],
    "en": ["Far-left ①", "Far-right ②", "Near-right ③", "Near-left ④"],
}

# ------------------------------------------------------------------ i18n
# "界面" scope: interactive controls, labels, hints and short status messages
# are translated. AI-generated content (report text, coach answers, charts,
# scorecards) is left as produced — retranslating model output is a separate,
# much larger concern than switching the interface language.
STRINGS = {
    "brand_status_local": {"zh": "本地运行 · 数据仅在本机", "en": "Runs locally · data never leaves this machine"},
    "brand_status_model": {"zh": "模型状态：", "en": "Model status: "},
    "brand_status_healthy": {"zh": "健康", "en": "Healthy"},
    "lang_toggle": {"zh": "EN", "en": "zh"},

    "step1_title": {"zh": "上传视频", "en": "Upload video"},
    "video_label": {"zh": "训练视频", "en": "Training video"},
    "load_frame_btn": {"zh": "读取第一帧", "en": "Load first frame"},
    "step2_title": {"zh": "标注剑道", "en": "Annotate piste"},
    "step2_hint": {"zh": "远左 → 远右 → 近右 → 近左，点击主画布完成四角标注。",
                   "en": "Far-left → far-right → near-right → near-left. Click the canvas to mark all four corners."},
    "clear_corners_btn": {"zh": "编辑剑道区域", "en": "Edit piste area"},
    "step3_title": {"zh": "运行分析", "en": "Run analysis"},
    "step3_hint": {"zh": "视频检测、事件识别与成绩卡会在本机完成。", "en": "Detection, event recognition and the scorecard all run locally."},

    "canvas_toolbar_title": {"zh": "视频画布 · 剑道标注与复盘", "en": "Video canvas · piste annotation & replay"},
    "canvas_toolbar_sub": {"zh": "固定侧拍 · 本地处理", "en": "Fixed side view · local processing"},
    "frame_img_label": {"zh": "第一帧 — 点击剑道 4 角点", "en": "First frame — click the 4 piste corners"},
    "status_upload_first": {"zh": "上传视频后读取第一帧，再在画布中完成剑道标注。",
                             "en": "Upload a video and load the first frame, then annotate the piste on the canvas."},
    "status_click_corners": {"zh": "在图上按顺序点击剑道 4 个角点:{labels}",
                              "en": "Click the 4 piste corners in order on the image: {labels}"},
    "status_progress": {"zh": "已标 {n}/4,下一个:{label}", "en": "Marked {n}/4, next: {label}"},
    "status_done": {"zh": "4 个角点完成,可以开始分析。", "en": "All 4 corners marked, ready to analyze."},
    "status_need_frame": {"zh": "请先读取第一帧。", "en": "Load the first frame first."},
    "status_redo_hint": {"zh": "已有 4 个角点,如需重标请点「清除角点」。", "en": "4 corners already set. Click \"Clear corners\" to redo."},
    "status_cleared": {"zh": "角点已清除,请重新标注。", "en": "Corners cleared, please re-annotate."},
    "status_no_video": {"zh": "请先上传视频。", "en": "Please upload a video first."},
    "status_no_frame_read": {"zh": "无法读取视频第一帧。", "en": "Could not read the first frame of the video."},

    "video_out_label": {"zh": "分析回放（左橙 L / 右青 R 剑尖）", "en": "Analysis replay (orange = left tip, cyan = right tip)"},

    "tab_summary": {"zh": "摘要", "en": "Summary"},
    "tab_charts": {"zh": "图表", "en": "Charts"},
    "tab_report": {"zh": "训练报告", "en": "Report"},
    "tab_evidence": {"zh": "证据", "en": "Evidence"},

    "charts_gallery_label": {"zh": "分析图表", "en": "Charts"},
    "evidence_intro": {"zh": "**事件时间证据** · 不生成独立视频切片，直接在主视频画布回放。",
                        "en": "**Event time evidence** · no separate clips — replay happens directly on the main canvas."},
    "evidence_dropdown_label": {"zh": "事件时间段", "en": "Event window"},
    "evidence_play_btn": {"zh": "播放此时间段", "en": "Play this window"},
    "evidence_select_prompt": {"zh": "请选择一个事件时间段。", "en": "Please select an event window."},
    "evidence_located": {"zh": "**{label}**  \n已定位到主视频画布；点击播放或使用“播放此时间段”。",
                          "en": "**{label}**  \nLocated on the main canvas; press play or use \"Play this window\"."},
    "evidence_invalid": {"zh": "事件时间段无效，请重新选择。", "en": "Invalid event window, please reselect."},
    "timeline_placeholder": {"zh": "分析完成后将在这里显示比赛事件时间线。",
                              "en": "The match event timeline will appear here after analysis."},
    "scorecard_placeholder": {"zh": "分析完成后在此显示单场成绩卡与三条训练重点。",
                               "en": "The scorecard and top 3 training priorities will appear here after analysis."},
    "evidence_detail_placeholder": {"zh": "分析完成后可选择事件时间段。",
                                     "en": "Event time windows become selectable after analysis."},

    "readiness_title": {"zh": "分析准备", "en": "Readiness"},
    "readiness_video": {"zh": "视频可读", "en": "Video loaded"},
    "readiness_corners": {"zh": "剑道区域", "en": "Piste area"},
    "readiness_fencer_detect": {"zh": "运动员检测", "en": "Fencer detection"},
    "readiness_kp_model": {"zh": "关键点模型", "en": "Keypoint model"},
    "readiness_ready": {"zh": "就绪", "en": "Ready"},
    "readiness_pending": {"zh": "待处理", "en": "Pending"},

    "match_settings_title": {"zh": "比赛设置", "en": "Match settings"},
    "weapon_note": {"zh": "剑种细分规则尚未实现，当前统一使用通用规则分析。",
                     "en": "Weapon-specific rules aren't implemented yet; general rules are used for all weapons."},
    "piste_length_label": {"zh": "标注剑道长度（米）", "en": "Annotated piste length (m)"},
    "detector_settings_title": {"zh": "检测器设置", "en": "Detector settings"},
    "blade_detector_label": {"zh": "剑尖检测器", "en": "Blade-tip detector"},
    "blade_filter_label": {"zh": "轨迹滤波", "en": "Trajectory filter"},
    "blade_model_path_label": {"zh": "训练权重路径（可选）", "en": "Trained weights path (optional)"},
    "vlm_rag_accordion": {"zh": "VLM 设置", "en": "VLM settings"},
    "vlm_enabled_label": {"zh": "启用 VLM 事件复核（较慢）", "en": "Enable VLM event review (slower)"},
    "vlm_provider_label": {"zh": "VLM 服务", "en": "VLM provider"},
    "vlm_base_url_label": {"zh": "服务地址", "en": "Service URL"},
    "vlm_model_label": {"zh": "VLM 视觉模型", "en": "VLM vision model"},
    "api_key_label": {"zh": "API Key（仅当前会话）", "en": "API key (current session only)"},
    "api_key_hint": {"zh": "留空时使用服务器私有环境配置；输入值不会写入场次、日志或仓库。",
                     "en": "Blank uses the server's private environment setting. Entered values are not saved to sessions, logs, or the repository."},
    "max_events_label": {"zh": "最多复核事件数", "en": "Max events to review"},
    "vlm_hint": {"zh": "VLM 只在分析完成后检查证据关键帧；关闭时保留纯规则分析。",
                 "en": "The VLM only reviews evidence keyframes after analysis; disable it to keep pure rule-based analysis."},
    "vlm_provider_hint": {"zh": "llama.cpp 模式下模型名仅作标识，实际权重由 llama-server 加载决定。",
                           "en": "For llama.cpp, the model name is just a label — the actual weights are whatever llama-server has loaded."},
    "run_analysis_btn": {"zh": "开始分析", "en": "Start analysis"},
    "privacy_card_title": {"zh": "本地隐私模式", "en": "Local privacy mode"},
    "privacy_card_body": {"zh": "视频、推理、知识库与教练对话均留在本机。",
                           "en": "Video, inference, knowledge base and coach chat all stay on this machine."},

    "coach_title": {"zh": "教练问答", "en": "Coach chat"},
    "chatbot_label": {"zh": "教练", "en": "Coach"},
    "coach_examples": {"zh": "可问：步法使用情况如何？ · 剑尖轨迹为何不稳定？ · 生成整场训练摘要",
                        "en": "Try asking: How was the footwork? · Why is the blade-tip trajectory unstable? · Summarize the whole session"},
    "rag_accordion": {"zh": "RAG 设置", "en": "RAG settings"},
    "rag_enabled_label": {"zh": "启用本地击剑知识库检索", "en": "Enable local fencing knowledge retrieval"},
    "rag_model_label": {"zh": "RAG 回答模型", "en": "RAG answer model"},
    "rag_answer_provider_label": {"zh": "RAG 回答服务", "en": "RAG answer provider"},
    "rag_answer_base_url_label": {"zh": "RAG 回答服务地址", "en": "RAG answer service URL"},
    "rag_provider_label": {"zh": "嵌入服务", "en": "Embedding provider"},
    "rag_base_url_label": {"zh": "嵌入服务地址", "en": "Embedding service URL"},
    "rag_embed_model_label": {"zh": "嵌入模型", "en": "Embedding model"},
    "rag_hint": {"zh": "索引：knowledge/.index（知识库）+ outputs/.session_index（场次归档）。嵌入服务与下方回答模型可分别配置、各用不同 provider。",
                 "en": "Index: knowledge/.index (knowledge base) + outputs/.session_index (session archive). The embedding service and the answer model above are configured independently and may use different providers."},
    "chat_placeholder": {"zh": "输入你的问题…", "en": "Type your question…"},
    "send_btn": {"zh": "发送", "en": "Send"},
    "reset_btn": {"zh": "清空", "en": "Clear"},
    "coach_start_failed": {"zh": "教练 Agent 启动失败(本地模型服务未就绪?): {exc}",
                            "en": "Coach agent failed to start (local model service not ready?): {exc}"},
    "coach_thinking": {"zh": "分析中…", "en": "Thinking…"},
    "coach_no_answer": {"zh": "(无回答)", "en": "(no answer)"},

    "archive_accordion": {"zh": "场次归档", "en": "Session archive"},
    "session_dd_label": {"zh": "已分析场次", "en": "Analyzed sessions"},
    "refresh_btn": {"zh": "刷新列表", "en": "Refresh list"},
    "tab_session_scorecard": {"zh": "单场成绩卡", "en": "Scorecard"},
    "tab_session_video": {"zh": "标注视频", "en": "Annotated video"},
    "tab_session_charts": {"zh": "图表", "en": "Charts"},
    "tab_session_report": {"zh": "报告", "en": "Report"},
    "tab_session_evidence": {"zh": "事件时间", "en": "Event timeline"},
    "session_select_prompt": {"zh": "请选择场次。", "en": "Please select a session."},
    "session_load_failed": {"zh": "读取失败: {exc}", "en": "Failed to load: {exc}"},

    "analyze_no_video": {"zh": "请先上传视频。", "en": "Please upload a video first."},
    "analyze_no_corners": {"zh": "请先在第一帧上标注 4 个剑道角点。", "en": "Please annotate the 4 piste corners on the first frame first."},
    "analyze_failed": {"zh": "分析失败: {exc}", "en": "Analysis failed: {exc}"},
    "analyze_no_report": {"zh": "(未生成报告)", "en": "(no report generated)"},
    "analyze_select_evidence": {"zh": "请选择事件时间段后，主视频画布会跳转并播放。",
                                 "en": "Select an event window and the main canvas will seek and play it."},
    "progress_desc": {"zh": "感知遍 {done}/{total} 帧", "en": "Perception pass {done}/{total} frames"},
}


def t(key, lang="zh"):
    return STRINGS[key].get(lang, STRINGS[key]["zh"])


# ------------------------------------------------------------------ visual identity
# Palette drawn from the product's own overlay language: arena dark, piste
# strip, orange (left tip) / cyan (right tip) dual accents.
CSS = """
:root { --sf-ink:#060a0e; --sf-panel:#10161e; --sf-panel-2:#151d27; --sf-line:#273342; --sf-muted:#8996a5; --sf-text:#edf3f8; --sf-orange:#ff7417; --sf-cyan:#1abfd1; --sf-green:#36c486; }
body,.gradio-container { background:var(--sf-ink)!important; color:var(--sf-text)!important; }
.gradio-container { max-width:none!important; padding:0 9px 20px!important; font-family:"IBM Plex Sans","Noto Sans SC",system-ui,sans-serif!important; --background-fill-primary:#0b1118!important; --background-fill-secondary:#10161e!important; --block-background-fill:#10161e!important; --block-label-background-fill:#10161e!important; --body-text-color:#edf3f8!important; --body-text-color-subdued:#8f9baa!important; --input-background-fill:#0a1017!important; --color-accent-soft:#1d1710!important; --border-color-primary:#2a3746!important; --border-color-accent:#ff7417!important; --button-secondary-background-fill:#25303d!important; --button-secondary-background-fill-hover:#303e4e!important; --button-secondary-text-color:#e1e8ee!important; }
.sf-header { height:54px; display:flex;align-items:center;justify-content:flex-start;gap:20px;padding:0 18px;border:1px solid #1d2833;border-radius:0 0 5px 5px;background:#05080b;margin:0 -9px 12px; }
.sf-brand { font-size:24px;font-weight:760;font-style:italic;letter-spacing:-.9px;color:#f8fafc;padding-right:22px;border-right:1px solid #2c3641; }.sf-brand b{color:var(--sf-orange)}.sf-brand em{font-style:inherit;color:var(--sf-orange)}
.sf-statuses{display:flex;align-items:center;gap:20px;color:var(--sf-muted);font-size:12px}.sf-statuses strong{color:#62cc9a;font-weight:650}.sf-dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin:0 6px 1px;background:var(--sf-green);box-shadow:0 0 12px rgba(54,196,134,.65)}
.sf-workspace{gap:9px!important;align-items:stretch!important}.sf-rail,.sf-inspector,.sf-coach,.sf-results,.sf-session-shell{background:var(--sf-panel)!important;border:1px solid var(--sf-line)!important;border-radius:7px!important;padding:10px!important;box-shadow:0 12px 32px rgba(0,0,0,.18)}.sf-canvas{background:#070b10!important;border:1px solid var(--sf-line)!important;border-radius:7px!important;padding:0!important;overflow:hidden}.sf-center{gap:9px!important}#sf-workspace.sf-coach-collapsed .sf-coach{display:none!important}#sf-workspace.sf-coach-collapsed .sf-center{flex-grow:48!important}
.sf-step{color:var(--sf-text);font-size:15px;font-weight:680;margin:13px 0 12px;display:flex;align-items:center;gap:10px}.sf-step span{width:29px;height:29px;border:1.5px solid var(--sf-orange);border-radius:50%;color:var(--sf-orange);display:inline-flex;justify-content:center;align-items:center;font-size:16px;font-weight:500}.sf-step.done span{border-color:var(--sf-green);color:var(--sf-green)}.sf-step.done{color:#d7eee2}.sf-step.current{color:#fff}
.sf-hint{color:var(--sf-muted);font-size:12px;line-height:1.55;margin:3px 0 11px}.sf-rail hr,.sf-inspector hr{border:0;border-top:1px solid var(--sf-line);margin:15px 0}.sf-rail .wrap,.sf-inspector .wrap{gap:8px!important}.sf-mini{font-size:11px;color:var(--sf-muted);line-height:1.65}.sf-ok{color:var(--sf-green);font-size:12px}.sf-toolbar{display:flex;justify-content:space-between;align-items:center;height:43px;padding:0 13px;border-bottom:1px solid var(--sf-line);background:#0c1117;color:#cfd8e1;font-size:12px}.sf-toolbar b{font-weight:650}.sf-toolbar span{color:var(--sf-muted)}
.sf-settings-accordion,.sf-rag-settings-accordion{border:1px solid #70401f!important;border-radius:7px!important;background:#16110d!important;overflow:hidden!important}.sf-settings-accordion>button,.sf-rag-settings-accordion>button,.sf-settings-accordion>button *,.sf-rag-settings-accordion>button *{color:#ff9b54!important;opacity:1!important;font-weight:700!important;text-shadow:0 1px 0 rgba(0,0,0,.45)!important}.sf-settings-accordion>button,.sf-rag-settings-accordion>button{background:#24170f!important;min-height:38px!important}.sf-settings-accordion>button:hover,.sf-rag-settings-accordion>button:hover{background:#302015!important;border-color:#ff7417!important}.sf-settings-accordion .wrap,.sf-rag-settings-accordion .wrap{padding-top:8px!important}
.sf-canvas .image-container,.sf-canvas .image-container img{background:#06090d!important}.sf-canvas .block{border:0!important}.sf-canvas .wrap{padding:0!important}.sf-canvas .label-wrap{display:none!important}.sf-player{border-top:1px solid var(--sf-line)!important;background:#080d13!important}.sf-player .label-wrap{display:none!important}.sf-player video{max-height:410px!important}.sf-results{padding:0!important;overflow:hidden}.sf-results .tab-nav{padding:0 12px;border-bottom:1px solid var(--sf-line)!important;background:#0c1117!important}.sf-results button{font-size:12px!important;color:#9aa7b6!important}.sf-results button.selected{color:#fff!important;border-bottom:2px solid var(--sf-orange)!important}.sf-results .tabitem{padding:12px!important;min-height:235px}
.sf-match-timeline{padding:2px 2px 10px}.sf-timeline-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin:1px 0 13px}.sf-timeline-head b{font-size:14px;color:#edf3f8}.sf-timeline-head small{display:block;color:var(--sf-muted);font-size:11px;margin-top:4px}.sf-timeline-legend{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:10px;color:#96a5b4;font-size:11px}.sf-timeline-legend span:before{content:"";display:inline-block;width:7px;height:7px;border-radius:1px;background:#758394;margin-right:4px}.sf-timeline-legend .attack:before,.sf-timeline-marker.attack{background:#ff7b4a}.sf-timeline-legend .lunge:before,.sf-timeline-marker.lunge{background:#ffd15c}.sf-timeline-legend .counter:before,.sf-timeline-marker.counter{background:#328fdd}.sf-timeline-legend .defense:before,.sf-timeline-marker.defense{background:#33c29d}.sf-timeline-track{height:45px;position:relative;margin:0 8px;background:linear-gradient(180deg,rgba(21,31,42,.94),rgba(12,18,26,.94));border-top:1px solid #46525f;border-bottom:1px solid #273440}.sf-timeline-track:after{content:"";position:absolute;left:0;right:0;top:22px;border-top:1px solid #566473}.sf-timeline-marker{position:absolute;z-index:1;top:8px;width:3px;height:29px;border-radius:2px;box-shadow:0 0 9px currentColor;transform:translateX(-50%)}.sf-timeline-marker.attack{color:#ff7b4a}.sf-timeline-marker.lunge{color:#ffd15c}.sf-timeline-marker.counter{color:#328fdd}.sf-timeline-marker.defense{color:#33c29d}.sf-timeline-ticks{height:25px;position:relative;margin:0 8px;color:#7f8e9d;font-size:10px}.sf-timeline-ticks span{position:absolute;top:5px;transform:translateX(-50%);white-space:nowrap}.sf-timeline-ticks span:before{content:"";position:absolute;left:50%;top:-6px;height:5px;border-left:1px solid #536171}.sf-timeline-ticks span:first-child{transform:none}.sf-timeline-ticks span:last-child{transform:translateX(-100%)}.sf-timeline-empty{font-size:12px;color:#91a0af;padding:16px 12px;background:#0c131a;border:1px dashed #344352;border-radius:5px}
.sf-local-card{border-left:3px solid var(--sf-green);padding:9px 10px;background:#0b1916;border-radius:3px 6px 6px 3px;color:#bce5cd;font-size:12px;line-height:1.55;margin-bottom:12px}.sf-local-card b{color:#e0fae9}.sf-section-title{font-size:13px;font-weight:700;letter-spacing:.04em;color:#e0e6ed;margin:4px 0 10px}.sf-check{font-size:12px;color:#b4c1cd;padding:7px 0;border-bottom:1px solid rgba(39,51,66,.65)}.sf-check b{float:right;font-weight:500;color:#8fa0af}.sf-check i{color:var(--sf-green);font-style:normal;margin-right:6px}
.sf-coach{display:flex;flex-direction:column;min-height:720px}.sf-coach-title{font-size:16px;font-weight:700;padding:2px 0 12px;border-bottom:1px solid var(--sf-line);margin-bottom:10px}.sf-coach .wrap{gap:8px!important}.sf-coach .message{border-radius:8px!important}.sf-coach .message-row{font-size:13px!important}.sf-coach .block-label{display:none!important}.sf-examples{font-size:12px;color:#a9b7c4;padding:9px 10px;background:#0d131a;border:1px solid #293543;border-radius:6px;margin-top:6px}.sf-tool-chip{display:inline-block;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;border:1px solid #314151;border-left:3px solid var(--sf-green);border-radius:5px;padding:3px 6px;margin:2px;color:#b8c7d6;background:#121a24}
.sf-coach-toggle{position:absolute!important;right:20px;top:10px;z-index:5;width:34px!important;min-width:34px!important}.sf-coach-toggle button{min-height:32px!important;width:34px!important;min-width:34px!important;padding:0!important;font-size:18px!important;line-height:1!important;background:#111923!important;border-color:#334151!important}.sf-coach-toggle button:hover{border-color:#ff7417!important;color:#ff8c43!important}
.sf-lang-toggle{position:absolute!important;right:62px;top:10px;z-index:5;width:40px!important;min-width:40px!important}.sf-lang-toggle button{min-height:32px!important;width:40px!important;min-width:40px!important;padding:0!important;font-size:12px!important;font-weight:700!important;line-height:1!important;background:#111923!important;border-color:#334151!important;color:#cfd8e1!important}.sf-lang-toggle button:hover{border-color:#ff7417!important;color:#ff8c43!important}
.gr-button-primary,.gradio-container button.primary{background:var(--sf-orange)!important;border:0!important;color:#fff!important;font-weight:720!important;min-height:42px!important}.gr-button-secondary,.gradio-container button.secondary{background:#25303d!important;border:1px solid #384657!important;color:#e1e8ee!important}.gradio-container button.secondary:hover{background:#303e4e!important}.gr-input,textarea,input,select,.gradio-container .block,.gradio-container .wrap{border-color:#33404f!important;color:var(--sf-text)!important}.gradio-container input:not([type=checkbox]):not([type=radio]),.gradio-container textarea,.gradio-container select{background:#0a1017!important;color:var(--sf-text)!important}.gradio-container .message{background:#151d27!important;color:#eaf0f5!important;border-color:#2b3847!important}.gradio-container .prose,.gradio-container .prose *{color:var(--sf-text)!important}label span,.block-label{color:#b8c3cf!important;font-size:12px!important}.sf-inspector .slider-container{padding-top:3px!important}.sf-inspector .checkbox{font-size:12px!important}.sf-archive{margin-top:10px}.sf-archive summary{font-weight:650;color:#c9d4df}footer{display:none!important}
.gradio-container input[type=checkbox],.gradio-container input[type=radio]{accent-color:var(--sf-orange)!important;width:16px!important;height:16px!important;cursor:pointer!important}
@media(max-width:1250px){.sf-workspace{flex-wrap:wrap!important}.sf-coach{min-height:520px}.sf-rail{min-width:210px!important}.sf-center{min-width:520px!important}.sf-inspector{min-width:250px!important}.sf-coach{min-width:310px!important}}@media(max-width:780px){.gradio-container{padding:0 6px 16px!important}.sf-header{height:auto;align-items:flex-start;flex-direction:column;padding:12px 14px;gap:8px}.sf-statuses{gap:9px;flex-wrap:wrap}.sf-workspace{flex-direction:column!important}.sf-center,.sf-rail,.sf-inspector,.sf-coach{min-width:0!important}}
"""


def _header_html(lang):
    return f'''
<div class="sf-header">
  <div class="sf-brand">Spark<b>Fen</b><em>cer</em></div>
  <div class="sf-statuses">
    <span><strong>{t("brand_status_local", lang)}</strong></span>
    <span>{t("brand_status_model", lang)}<i class="sf-dot"></i><strong>{t("brand_status_healthy", lang)}</strong></span>
  </div>
</div>
'''


def _step1_html(lang):
    return f'<div class="sf-step current"><span>1</span>{t("step1_title", lang)}</div>'


def _step2_html(lang):
    return (f'<hr><div class="sf-step"><span>2</span>{t("step2_title", lang)}</div>'
            f'<p class="sf-hint">{t("step2_hint", lang)}</p>')


def _step3_html(lang):
    return (f'<hr><div class="sf-step"><span>3</span>{t("step3_title", lang)}</div>'
            f'<p class="sf-hint">{t("step3_hint", lang)}</p>')


def _toolbar_html(lang):
    return f'<div class="sf-toolbar"><b>{t("canvas_toolbar_title", lang)}</b><span>{t("canvas_toolbar_sub", lang)}</span></div>'


def _match_settings_html(lang):
    return (f'<hr><div class="sf-section-title">{t("match_settings_title", lang)}</div>'
            f'<p class="sf-mini">{t("weapon_note", lang)}</p>')


def _detector_settings_html(lang):
    return f'<hr><div class="sf-section-title">{t("detector_settings_title", lang)}</div>'


def _vlm_hint_html(lang):
    return f'<p class="sf-mini">{t("vlm_hint", lang)}</p>'


def _vlm_provider_hint_html(lang):
    return f'<p class="sf-mini">{t("vlm_provider_hint", lang)}</p>'


# Known-good defaults per backend; both speak the OpenAI-compatible
# /v1/chat/completions API so LocalVLMAgent works unmodified against either.
VLM_PROVIDER_PRESETS = {
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "models": ["qwen3-vl:32b", "llava:34b"],
    },
    "llama.cpp": {
        "base_url": "http://127.0.0.1:8090/v1",
        "models": ["MiniCPM-o-4_5-F16", "MiniCPM-o-4_5-Q8_0", "MiniCPM-o-4_5-Q4_K_M"],
    },
    "radeon cloud": {
        "base_url": "https://developer.amd.com.cn/radeon/api/v1",
        "models": ["Qwen3.6-35B-A3B"],
    },
}

# The answer model is separate from the local embedding service used to search
# the knowledge base.  Cloud text models belong here, not in embedding presets.
RAG_ANSWER_PROVIDER_PRESETS = {
    "ollama": {"base_url": "http://127.0.0.1:11434/v1", "models": ["qwen3:32b", "qwen3:14b"]},
    "llama.cpp": {"base_url": "http://127.0.0.1:8090/v1", "models": ["Qwen3-32B"]},
    "radeon cloud": {"base_url": "https://developer.amd.com.cn/radeon/api/v1",
                      "models": ["DeepSeek-V4-Flash"]},
}


def on_vlm_provider_change(provider):
    preset = VLM_PROVIDER_PRESETS.get(provider, VLM_PROVIDER_PRESETS["ollama"])
    return (gr.update(value=preset["base_url"]),
            gr.update(choices=preset["models"], value=preset["models"][0]))


def on_rag_answer_provider_change(provider):
    preset = RAG_ANSWER_PROVIDER_PRESETS.get(provider, RAG_ANSWER_PROVIDER_PRESETS["ollama"])
    return (gr.update(value=preset["base_url"]),
            gr.update(choices=preset["models"], value=preset["models"][0]))


# RAG embedding service: independent from the VLM/answer-model backend above —
# ollama uses its native /api/embed, llama.cpp needs a separate llama-server
# instance started with --embedding exposing OpenAI-compatible /v1/embeddings.
RAG_PROVIDER_PRESETS = {
    "ollama": {
        "base_url": "http://127.0.0.1:11434",
        "models": ["bge-m3"],
    },
    "llama.cpp": {
        "base_url": "http://127.0.0.1:8091",
        "models": ["bge-m3-GGUF"],
    },
}


def on_rag_provider_change(provider):
    preset = RAG_PROVIDER_PRESETS.get(provider, RAG_PROVIDER_PRESETS["ollama"])
    return (gr.update(value=preset["base_url"]),
            gr.update(choices=preset["models"], value=preset["models"][0]))


def _privacy_card_html(lang):
    return f'<div class="sf-local-card"><b>{t("privacy_card_title", lang)}</b><br>{t("privacy_card_body", lang)}</div>'


def _coach_title_html(lang):
    return f'<div class="sf-coach-title">{t("coach_title", lang)}</div>'


def _examples_html(lang):
    return f'<div class="sf-examples">{t("coach_examples", lang)}</div>'


def _rag_hint_html(lang):
    return f'<p class="sf-mini">{t("rag_hint", lang)}</p>'


def _readiness_html(video_ready, corners_ready, lang="zh"):
    def item(label, ready):
        state = t("readiness_ready", lang) if ready else t("readiness_pending", lang)
        return f'<div class="sf-check"><i>●</i>{label} <b>{state}</b></div>'
    return (
        f'<div class="sf-section-title">{t("readiness_title", lang)}</div>'
        + item(t("readiness_video", lang), video_ready)
        + item(t("readiness_corners", lang), corners_ready)
        + item(t("readiness_fencer_detect", lang), True)
        + item(t("readiness_kp_model", lang), True)
    )


def _status_message(has_frame, n_corners, lang):
    if not has_frame:
        text = t("status_upload_first", lang)
    elif n_corners == 0:
        text = t("status_click_corners", lang).format(labels=" → ".join(CORNER_LABELS[lang]))
    elif n_corners < 4:
        text = t("status_progress", lang).format(n=n_corners, label=CORNER_LABELS[lang][n_corners])
    else:
        text = t("status_done", lang)
    return f"<span class='sf-hint'>{text}</span>"


_coach = {}


def _get_coach(thread_id=None, model=None, enable_rag=True,
               rag_provider=None, rag_base_url=None, rag_embed_model=None,
               answer_base_url=None, answer_api_key=None):
    thread_id = thread_id or uuid.uuid4().hex
    rag_config = {"provider": rag_provider or "ollama", "base_url": rag_base_url or None,
                  "model": rag_embed_model or "bge-m3"}
    settings = (model or "qwen3:32b", answer_base_url or None, answer_api_key or None,
                bool(enable_rag), rag_config["provider"],
                rag_config["base_url"], rag_config["model"])
    cached = _coach.get(thread_id)
    if cached is None or cached[0] != settings:
        from fencing_analysis.agents.orchestrator import CoachChat
        _coach[thread_id] = (settings, CoachChat(thread_id=thread_id, model=settings[0],
                                                  base_url=settings[1], api_key=settings[2] or "none",
                                                  enable_rag=settings[3], rag_config=rag_config,
                                                  verbose=False))
    return thread_id, _coach[thread_id][1]


# ------------------------------------------------------------------ 视频分析页
def load_frame(video_file, lang):
    if not video_file:
        return None, [], t("status_no_video", lang)
    frame = read_first_frame(video_file)
    if frame is None:
        return None, [], t("status_no_frame_read", lang)
    return frame, [], _status_message(True, 0, lang)


def load_frame_ui(video_file, lang):
    """Show the annotation frame in the same canvas used for replay."""
    frame, corners, message = load_frame(video_file, lang)
    return (gr.update(value=frame, visible=True), corners, message,
            gr.update(value=None, visible=False), frame,
            _readiness_html(frame is not None, False, lang))


def _dashed_line(canvas, start, end, color, thickness=2, dash=16, gap=10):
    """Draw a readable guide without implying that it is a confirmed piste edge."""
    x1, y1 = map(float, start)
    x2, y2 = map(float, end)
    length = float(np.hypot(x2 - x1, y2 - y1))
    if length < 1:
        return
    dx, dy = (x2 - x1) / length, (y2 - y1) / length
    distance = 0.0
    while distance < length:
        segment_end = min(distance + dash, length)
        cv2.line(
            canvas,
            (int(round(x1 + dx * distance)), int(round(y1 + dy * distance))),
            (int(round(x1 + dx * segment_end)), int(round(y1 + dy * segment_end))),
            color,
            thickness,
            cv2.LINE_AA,
        )
        distance += dash + gap


def _corner_guides(frame_shape, corners):
    """Predict only the next corners from confirmed points for click guidance."""
    height, width = frame_shape[:2]
    margin = max(18, int(min(height, width) * 0.035))
    if len(corners) == 1:
        x1, y1 = corners[0]
        # A provisional rectangle makes all three remaining click targets visible.
        p2 = (width - margin, y1)
        p4 = (x1, height - margin)
        return [(p2, "2"), ((p2[0], p4[1]), "3"), (p4, "4")], [
            (tuple(corners[0]), p2),
            (p2, (p2[0], p4[1])),
            ((p2[0], p4[1]), p4),
            (p4, tuple(corners[0])),
        ]
    if len(corners) == 2:
        p1, p2 = map(tuple, corners)
        depth = max(int(height * 0.42), int(abs(p2[0] - p1[0]) * 0.18))
        guide_y = min(height - margin, max(p1[1], p2[1]) + depth)
        p3, p4 = (p2[0], guide_y), (p1[0], guide_y)
        return [(p3, "3"), (p4, "4")], [(p2, p3), (p3, p4), (p4, p1)]
    if len(corners) == 3:
        p1, _, p3 = map(tuple, corners)
        p4 = (p1[0], p3[1])
        return [(p4, "4")], [(p3, p4), (p4, p1)]
    return [], []


def _draw_corners(frame, corners):
    canvas = frame.copy()
    actual = [tuple(map(int, point)) for point in corners]

    # Confirmed edges stay green; amber dashed edges are only click guidance.
    if len(actual) > 1:
        cv2.polylines(canvas, [np.array(actual, dtype=np.int32)], len(actual) == 4,
                      (60, 200, 90), 2, cv2.LINE_AA)
    if 0 < len(actual) < 4:
        guide_points, guide_edges = _corner_guides(canvas.shape, actual)
        for start, end in guide_edges:
            _dashed_line(canvas, start, end, (0, 190, 255))
        for (x, y), label in guide_points:
            cv2.circle(canvas, (int(x), int(y)), 10, (0, 190, 255), 2, cv2.LINE_AA)
            label_x = int(x) - 32 if x > canvas.shape[1] - 48 else int(x) + 12
            cv2.putText(canvas, label, (label_x, int(y) - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 190, 255), 2, cv2.LINE_AA)
    for idx, (x, y) in enumerate(actual, 1):
        cv2.circle(canvas, (x, y), 8, (255, 60, 40), -1, cv2.LINE_AA)
        cv2.putText(canvas, str(idx), (x + 10, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 60, 40), 3, cv2.LINE_AA)
    return canvas


def on_click(frame, corners, lang, evt: gr.SelectData):
    if frame is None:
        return None, corners, t("status_need_frame", lang), _readiness_html(False, False, lang)
    if len(corners) >= 4:
        return (_draw_corners(frame, corners), corners, t("status_redo_hint", lang),
                _readiness_html(True, True, lang))
    corners = corners + [[int(evt.index[0]), int(evt.index[1])]]
    msg = _status_message(True, len(corners), lang)
    return _draw_corners(frame, corners), corners, msg, _readiness_html(True, len(corners) == 4, lang)


def clear_corners(frame, lang):
    if frame is None:
        return None, [], t("status_need_frame", lang), _readiness_html(False, False, lang)
    return frame, [], t("status_cleared", lang), _readiness_html(True, False, lang)


def evidence_window_message(selection, lang):
    """Render the selected time window; seeking happens in the browser player."""
    if not selection:
        return t("evidence_select_prompt", lang)
    try:
        event = json.loads(selection)
        return t("evidence_located", lang).format(label=event["label"])
    except (TypeError, ValueError, KeyError):
        return t("evidence_invalid", lang)


PLAY_EVIDENCE_JS = r"""
(selection) => {
  if (!selection) return selection;
  try {
    const event = JSON.parse(selection);
    const player = document.querySelector('#analysis-video video');
    if (!player) return selection;
    window.sparkFencerEvidenceStop && clearInterval(window.sparkFencerEvidenceStop);
    player.currentTime = Number(event.start) || 0;
    const stopAt = Number(event.end) || player.duration;
    const started = player.play();
    if (started && started.catch) started.catch(() => {});
    window.sparkFencerEvidenceStop = setInterval(() => {
      if (player.currentTime >= stopAt || player.ended) {
        player.pause();
        clearInterval(window.sparkFencerEvidenceStop);
        window.sparkFencerEvidenceStop = null;
      }
    }, 80);
  } catch (_) {}
  return selection;
}
"""


COACH_LAYOUT_JS = r"""
(visible) => {
  document.getElementById('sf-workspace')?.classList.toggle('sf-coach-collapsed');
  return visible;
}
"""


def analyze(video_file, frame, corners, piste_length, blade_detector,
            blade_filter, blade_model_path, vlm_enabled, vlm_base_url, vlm_model, vlm_api_key, max_events, lang,
    progress=gr.Progress()):
    if not video_file:
        return gr.update(), t("analyze_no_video", lang), "", "", [], gr.update(), "", gr.update()
    if len(corners) != 4:
        return gr.update(), t("analyze_no_corners", lang), "", "", [], gr.update(), "", gr.update()

    def progress_cb(done, total):
        if total and done % 30 == 0:
            progress(done / total, desc=t("progress_desc", lang).format(done=done, total=total))

    try:
        result = run_webui_analysis(
            video_file, [tuple(c) for c in corners], piste_length, "general",
            skip_agents=not vlm_enabled, blade_detector=blade_detector, blade_filter=blade_filter,
            blade_model_path=(blade_model_path or None),
            vlm_base_url=(vlm_base_url or None), vlm_model=(vlm_model or None),
            vlm_api_key=(vlm_api_key or None),
            max_events_to_review=max_events, lang=lang,
            progress_cb=progress_cb,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return gr.update(), t("analyze_failed", lang).format(exc=exc), "", "", [], gr.update(), "", gr.update()
    return (gr.update(value=result["video"], visible=True), result["scorecard"],
            result["timeline"], result["report"] or t("analyze_no_report", lang), result["charts"],
            gr.update(choices=result["evidence_choices"], value=None),
            t("analyze_select_evidence", lang),
            gr.update(visible=False))


# ------------------------------------------------------------------ 教练问答页
def chat_fn(message, history, thread_id, rag_enabled, rag_model, rag_answer_base_url,
           rag_api_key, rag_provider, rag_base_url, rag_embed_model, lang):
    message = (message or "").strip()
    if not message:
        yield history, "", thread_id
        return
    history = list(history) + [{"role": "user", "content": message}]
    yield history, "", thread_id
    try:
        thread_id, coach = _get_coach(thread_id, model=rag_model, enable_rag=rag_enabled,
                                      rag_provider=rag_provider, rag_base_url=rag_base_url,
                                      rag_embed_model=rag_embed_model,
                                      answer_base_url=rag_answer_base_url,
                                      answer_api_key=rag_api_key)
    except Exception as exc:
        yield history + [{"role": "assistant",
                          "content": t("coach_start_failed", lang).format(exc=exc)}], "", thread_id
        return

    chips = []
    answer = None
    for kind, text in coach.ask_stream(message):
        if kind == "tool":
            chips.append(f'<span class="sf-tool-chip">🔧 {text}</span>')
            status = "<br>".join(chips) + f"<br><em>{t('coach_thinking', lang)}</em>"
            yield history + [{"role": "assistant", "content": status}], "", thread_id
        else:
            answer = text
    body = ("<br>".join(chips) + "\n\n" if chips else "") + (answer or t("coach_no_answer", lang))
    yield history + [{"role": "assistant", "content": body}], "", thread_id


def reset_chat(thread_id):
    cached = _coach.pop(thread_id, None)
    if cached is not None:
        cached[1].clear_memory()
    return [], "", None


def toggle_coach(visible):
    """Update the icon/state; the browser removes the entire flex column."""
    shown = not bool(visible)
    return shown, gr.update(value="◀" if shown else "▶")


# ------------------------------------------------------------------ 场次浏览页
def refresh_sessions():
    sessions = list_sessions_info()
    names = [s["name"] for s in sessions]
    return gr.update(choices=names, value=names[0] if names else None)


def show_session(name, lang):
    if not name:
        return t("session_select_prompt", lang), "", None, [], "", []
    try:
        return load_session_assets(name, lang=lang)
    except Exception as exc:
        return t("session_load_failed", lang).format(exc=exc), "", None, [], "", []


# ------------------------------------------------------------------ 组装
def build_app():
    theme = gr.themes.Soft(
        primary_hue="orange", secondary_hue="cyan", neutral_hue="slate",
        font=[gr.themes.GoogleFont("IBM Plex Sans"), "Noto Sans SC", "system-ui", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("IBM Plex Mono"), "ui-monospace", "monospace"],
    ).set(
        # Soft's dark-mode block-label chip defaults to a solid primary-hue fill
        # (block_label_background_fill_dark="*primary_600"), which turns every
        # field label into a loud orange badge once primary_hue="orange" is set
        # for button branding. Rein that in to a subtle, panel-matching chip so
        # orange stays reserved for actual CTAs/accents. Both light/dark variants
        # are set since this page always forces the dark palette.
        block_label_background_fill="#141b24", block_label_background_fill_dark="#141b24",
        block_label_text_color="#9aa7b6", block_label_text_color_dark="#9aa7b6",
        block_label_border_color="#273342", block_label_border_color_dark="#273342",
    )
    with gr.Blocks(title="SparkFencer", theme=theme, css=CSS) as demo:
        lang_state = gr.State("zh")
        header_html = gr.HTML(_header_html("zh"))
        lang_toggle_btn = gr.Button(t("lang_toggle", "zh"), variant="secondary", elem_id="lang-toggle",
                                     elem_classes="sf-lang-toggle")
        coach_toggle = gr.Button("◀", variant="secondary", elem_id="coach-toggle",
                                 elem_classes="sf-coach-toggle")
        coach_visible = gr.State(value=True)

        with gr.Row(elem_id="sf-workspace", elem_classes="sf-workspace"):
            with gr.Column(scale=13, min_width=195, elem_classes="sf-rail"):
                step1_html = gr.HTML(_step1_html("zh"))
                video_in = gr.Video(label=t("video_label"), sources=["upload"])
                load_btn = gr.Button(t("load_frame_btn"), variant="secondary")
                step2_html = gr.HTML(_step2_html("zh"))
                clear_btn = gr.Button(t("clear_corners_btn"), variant="secondary")
                step3_html = gr.HTML(_step3_html("zh"))

            with gr.Column(scale=48, min_width=570, elem_classes="sf-center"):
                with gr.Group(elem_classes="sf-canvas"):
                    toolbar_html = gr.HTML(_toolbar_html("zh"))
                    frame_img = gr.Image(label=t("frame_img_label"), interactive=False)
                    status = gr.Markdown(_status_message(False, 0, "zh"))
                    video_out = gr.Video(label=t("video_out_label"), elem_id="analysis-video",
                                         elem_classes="sf-player", visible=False)
                frame_state = gr.State(None)
                corners_state = gr.State([])
                with gr.Group(elem_classes="sf-results"):
                    with gr.Tabs():
                        with gr.Tab(t("tab_summary")) as tab_summary:
                            timeline_out = gr.HTML(f'<div class="sf-timeline-empty">{t("timeline_placeholder")}</div>')
                            scorecard_out = gr.Markdown(t("scorecard_placeholder"))
                        with gr.Tab(t("tab_charts")) as tab_charts:
                            charts_out = gr.Gallery(label=t("charts_gallery_label"), columns=2)
                        with gr.Tab(t("tab_report")) as tab_report:
                            report_out = gr.Markdown()
                        with gr.Tab(t("tab_evidence")) as tab_evidence:
                            evidence_intro_md = gr.Markdown(t("evidence_intro"))
                            evidence_choice = gr.Dropdown(label=t("evidence_dropdown_label"), choices=[], interactive=True)
                            play_evidence_btn = gr.Button(t("evidence_play_btn"), variant="secondary")
                            evidence_detail = gr.Markdown(t("evidence_detail_placeholder"))

            with gr.Column(scale=19, min_width=255, elem_classes="sf-inspector"):
                readiness_out = gr.HTML(_readiness_html(False, False, "zh"))
                match_settings_html = gr.HTML(_match_settings_html("zh"))
                piste_length = gr.Slider(4, 14, value=14, step=0.5, label=t("piste_length_label"))
                detector_settings_html = gr.HTML(_detector_settings_html("zh"))
                blade_detector = gr.Dropdown(["cv", "yolo", "pose"], value="cv", label=t("blade_detector_label"))
                blade_filter = gr.Dropdown(["kalman", "ema", "none"], value="kalman", label=t("blade_filter_label"))
                blade_model_path = gr.Textbox(label=t("blade_model_path_label"),
                                               placeholder="runs/blade_pose/.../best.pt")
                with gr.Accordion(t("vlm_rag_accordion"), open=False,
                                  elem_classes="sf-settings-accordion") as vlm_rag_accordion:
                    vlm_enabled = gr.Checkbox(label=t("vlm_enabled_label"), value=False)
                    default_vlm_provider = ("radeon cloud" if os.environ.get("VLM_BASE_URL", "").startswith("https://developer.amd.com.cn/")
                                            else "ollama")
                    vlm_provider = gr.Dropdown(["ollama", "llama.cpp", "radeon cloud"], value=default_vlm_provider,
                                               label=t("vlm_provider_label"))
                    vlm_base_url = gr.Textbox(value=VLM_PROVIDER_PRESETS[default_vlm_provider]["base_url"],
                                              label=t("vlm_base_url_label"))
                    vlm_model = gr.Dropdown(VLM_PROVIDER_PRESETS[default_vlm_provider]["models"],
                                            value=os.environ.get("VLM_MODEL", VLM_PROVIDER_PRESETS[default_vlm_provider]["models"][0]),
                                            allow_custom_value=True, label=t("vlm_model_label"))
                    vlm_api_key = gr.Textbox(type="password", value="",
                                             label=t("api_key_label"), info=t("api_key_hint"))
                    max_events = gr.Slider(2, 12, value=8, step=1, label=t("max_events_label"))
                    vlm_hint_html = gr.HTML(_vlm_hint_html("zh"))
                    vlm_provider_hint_html = gr.HTML(_vlm_provider_hint_html("zh"))
                run_btn = gr.Button(t("run_analysis_btn"), variant="primary")
                privacy_card_html = gr.HTML(_privacy_card_html("zh"))

            with gr.Column(scale=25, min_width=300, elem_classes="sf-coach") as coach_panel:
                coach_title_html = gr.HTML(_coach_title_html("zh"))
                chatbot = gr.Chatbot(height=430, label=t("chatbot_label"))
                thread_state = gr.State(value=None)
                examples_html = gr.HTML(_examples_html("zh"))
                with gr.Accordion(t("rag_accordion"), open=False,
                                  elem_classes="sf-rag-settings-accordion") as rag_accordion:
                    rag_enabled = gr.Checkbox(label=t("rag_enabled_label"), value=True)
                    default_rag_answer_provider = ("radeon cloud" if os.environ.get("VLM_BASE_URL", "").startswith("https://developer.amd.com.cn/")
                                                   else "ollama")
                    rag_answer_provider = gr.Dropdown(["ollama", "llama.cpp", "radeon cloud"],
                                                      value=default_rag_answer_provider,
                                                      label=t("rag_answer_provider_label"))
                    rag_answer_base_url = gr.Textbox(
                        value=RAG_ANSWER_PROVIDER_PRESETS[default_rag_answer_provider]["base_url"],
                        label=t("rag_answer_base_url_label"))
                    rag_model = gr.Dropdown(RAG_ANSWER_PROVIDER_PRESETS[default_rag_answer_provider]["models"],
                                            value=os.environ.get("AGENT_MODEL", RAG_ANSWER_PROVIDER_PRESETS[default_rag_answer_provider]["models"][0]),
                                            label=t("rag_model_label"))
                    rag_api_key = gr.Textbox(type="password", value="",
                                             label=t("api_key_label"), info=t("api_key_hint"))
                    rag_provider = gr.Dropdown(["ollama", "llama.cpp"], value="ollama",
                                               label=t("rag_provider_label"))
                    rag_base_url = gr.Textbox(value=RAG_PROVIDER_PRESETS["ollama"]["base_url"],
                                              label=t("rag_base_url_label"))
                    rag_embed_model = gr.Dropdown(RAG_PROVIDER_PRESETS["ollama"]["models"],
                                                  value=RAG_PROVIDER_PRESETS["ollama"]["models"][0],
                                                  allow_custom_value=True, label=t("rag_embed_model_label"))
                    rag_hint_html = gr.HTML(_rag_hint_html("zh"))
                chat_in = gr.Textbox(placeholder=t("chat_placeholder"), show_label=False)
                with gr.Row():
                    send_btn = gr.Button(t("send_btn"), variant="primary", scale=3)
                    reset_btn = gr.Button(t("reset_btn"), variant="secondary", scale=1)

        load_btn.click(load_frame_ui, [video_in, lang_state],
                       [frame_img, corners_state, status, video_out, frame_state, readiness_out])
        frame_img.select(on_click, [frame_state, corners_state, lang_state],
                          [frame_img, corners_state, status, readiness_out])
        clear_btn.click(clear_corners, [frame_state, lang_state],
                         [frame_img, corners_state, status, readiness_out])
        vlm_provider.change(on_vlm_provider_change, [vlm_provider], [vlm_base_url, vlm_model])
        rag_answer_provider.change(on_rag_answer_provider_change, [rag_answer_provider],
                                   [rag_answer_base_url, rag_model])
        rag_provider.change(on_rag_provider_change, [rag_provider], [rag_base_url, rag_embed_model])
        run_btn.click(analyze,
                      [video_in, frame_state, corners_state, piste_length,
                       blade_detector, blade_filter, blade_model_path, vlm_enabled,
                       vlm_base_url, vlm_model, vlm_api_key, max_events,
                       lang_state],
                      [video_out, scorecard_out, timeline_out, report_out, charts_out,
                       evidence_choice, evidence_detail, frame_img])
        evidence_choice.change(evidence_window_message, [evidence_choice, lang_state], [evidence_detail])
        play_evidence_btn.click(evidence_window_message, [evidence_choice, lang_state], [evidence_detail],
                                 js=PLAY_EVIDENCE_JS)
        rag_chat_inputs = [chat_in, chatbot, thread_state, rag_enabled, rag_model,
                          rag_answer_base_url, rag_api_key, rag_provider, rag_base_url,
                          rag_embed_model, lang_state]
        send_btn.click(chat_fn, rag_chat_inputs, [chatbot, chat_in, thread_state])
        chat_in.submit(chat_fn, rag_chat_inputs, [chatbot, chat_in, thread_state])
        reset_btn.click(reset_chat, [thread_state], [chatbot, chat_in, thread_state])
        coach_toggle.click(toggle_coach, [coach_visible], [coach_visible, coach_toggle], js=COACH_LAYOUT_JS)

        with gr.Accordion(t("archive_accordion"), open=False, elem_classes="sf-archive") as archive_accordion:
            with gr.Group(elem_classes="sf-session-shell"):
                with gr.Row():
                    session_dd = gr.Dropdown(label=t("session_dd_label"), choices=[], scale=4)
                    refresh_btn = gr.Button(t("refresh_btn"), scale=1, variant="secondary")
                overview_md = gr.Markdown()
                with gr.Tabs():
                    with gr.Tab(t("tab_session_scorecard")) as tab_session_scorecard:
                        s_scorecard = gr.Markdown()
                    with gr.Tab(t("tab_session_video")) as tab_session_video:
                        s_video = gr.Video()
                    with gr.Tab(t("tab_session_charts")) as tab_session_charts:
                        s_charts = gr.Gallery(columns=2)
                    with gr.Tab(t("tab_session_report")) as tab_session_report:
                        s_report = gr.Markdown()
                    with gr.Tab(t("tab_session_evidence")) as tab_session_evidence:
                        s_evidence = gr.Markdown()
                refresh_btn.click(refresh_sessions, [], [session_dd])
                session_dd.change(show_session, [session_dd, lang_state],
                                  [overview_md, s_scorecard, s_video, s_charts, s_report, s_evidence])
                demo.load(refresh_sessions, [], [session_dd])

        # ---------------------------------------------------------- language toggle
        # Only chrome (labels/buttons/hints) is retranslated here. Anything that
        # can hold already-computed analysis output (report, scorecard, timeline,
        # chat history, evidence detail, session panels) is deliberately excluded
        # so a language switch never overwrites real results with placeholder text.
        HTML_TARGETS = [
            (step1_html, _step1_html), (step2_html, _step2_html), (step3_html, _step3_html),
            (toolbar_html, _toolbar_html), (match_settings_html, _match_settings_html),
            (detector_settings_html, _detector_settings_html), (vlm_hint_html, _vlm_hint_html),
            (vlm_provider_hint_html, _vlm_provider_hint_html),
            (privacy_card_html, _privacy_card_html), (coach_title_html, _coach_title_html),
            (examples_html, _examples_html), (rag_hint_html, _rag_hint_html),
        ]
        LABEL_TARGETS = [
            (video_in, "video_label"), (frame_img, "frame_img_label"), (video_out, "video_out_label"),
            (tab_summary, "tab_summary"), (tab_charts, "tab_charts"), (charts_out, "charts_gallery_label"),
            (tab_report, "tab_report"), (tab_evidence, "tab_evidence"),
            (evidence_choice, "evidence_dropdown_label"),
            (piste_length, "piste_length_label"), (blade_detector, "blade_detector_label"),
            (blade_filter, "blade_filter_label"),
            (vlm_rag_accordion, "vlm_rag_accordion"), (vlm_enabled, "vlm_enabled_label"),
            (vlm_provider, "vlm_provider_label"), (vlm_base_url, "vlm_base_url_label"),
            (vlm_model, "vlm_model_label"), (vlm_api_key, "api_key_label"), (max_events, "max_events_label"),
            (chatbot, "chatbot_label"), (rag_accordion, "rag_accordion"),
            (rag_enabled, "rag_enabled_label"), (rag_answer_provider, "rag_answer_provider_label"),
            (rag_answer_base_url, "rag_answer_base_url_label"), (rag_model, "rag_model_label"),
            (rag_api_key, "api_key_label"),
            (rag_provider, "rag_provider_label"), (rag_base_url, "rag_base_url_label"),
            (rag_embed_model, "rag_embed_model_label"),
            (archive_accordion, "archive_accordion"), (session_dd, "session_dd_label"),
            (tab_session_scorecard, "tab_session_scorecard"), (tab_session_video, "tab_session_video"),
            (tab_session_charts, "tab_session_charts"), (tab_session_report, "tab_session_report"),
            (tab_session_evidence, "tab_session_evidence"),
        ]
        VALUE_TARGETS = [
            (load_btn, "load_frame_btn"), (clear_btn, "clear_corners_btn"),
            (play_evidence_btn, "evidence_play_btn"), (evidence_intro_md, "evidence_intro"),
            (run_btn, "run_analysis_btn"), (send_btn, "send_btn"), (reset_btn, "reset_btn"),
            (refresh_btn, "refresh_btn"),
        ]
        INFO_TARGETS = [
            (vlm_api_key, "api_key_hint"),
            (rag_api_key, "api_key_hint"),
        ]

        # Pre-analysis placeholder text (timeline/scorecard/evidence panels) is safe
        # to retranslate on a language switch; real analysis output in the same
        # components must never be overwritten, so we only swap the value when it
        # still exactly matches the placeholder text in the *old* language.
        PLACEHOLDER_TARGETS = [
            (timeline_out, "timeline_placeholder", lambda v: f'<div class="sf-timeline-empty">{v}</div>'),
            (scorecard_out, "scorecard_placeholder", None),
            (evidence_detail, "evidence_detail_placeholder", None),
        ]

        def _placeholder_update(current_value, key, old_lang, new_lang, wrap):
            old_text = wrap(t(key, old_lang)) if wrap else t(key, old_lang)
            if current_value == old_text:
                new_text = t(key, new_lang)
                return gr.update(value=wrap(new_text) if wrap else new_text)
            return gr.update()

        def set_language(current_lang, frame, corners, timeline_val, scorecard_val, evidence_val, session_name):
            new_lang = "en" if current_lang == "zh" else "zh"
            outputs = [gr.update(value=_header_html(new_lang)), gr.update(value=t("lang_toggle", new_lang))]
            outputs += [gr.update(value=fn(new_lang)) for _, fn in HTML_TARGETS]
            outputs += [gr.update(label=t(key, new_lang)) for _, key in LABEL_TARGETS]
            outputs += [gr.update(value=t(key, new_lang)) for _, key in VALUE_TARGETS]
            outputs += [gr.update(info=t(key, new_lang)) for _, key in INFO_TARGETS]
            outputs.append(gr.update(label=t("blade_model_path_label", new_lang)))
            outputs.append(gr.update(placeholder=t("chat_placeholder", new_lang)))
            outputs.append(_readiness_html(frame is not None, len(corners or []) == 4, new_lang))
            outputs.append(_status_message(frame is not None, len(corners or []), new_lang))
            for current_value, (_, key, wrap) in zip((timeline_val, scorecard_val, evidence_val), PLACEHOLDER_TARGETS):
                outputs.append(_placeholder_update(current_value, key, current_lang, new_lang, wrap))
            # Archive summaries are deterministic views over structured session
            # data, so reload only the summary in the new UI language. The
            # report, scorecard, gallery, and evidence are historical outputs
            # with their own component types and remain unchanged here.
            if session_name:
                try:
                    archive_overview = load_session_assets(session_name, lang=new_lang)[0]
                except Exception as exc:
                    archive_overview = t("session_load_failed", new_lang).format(exc=exc)
            else:
                archive_overview = t("session_select_prompt", new_lang)
            outputs.append(gr.update(value=archive_overview))
            outputs.append(new_lang)
            return outputs

        lang_toggle_btn.click(
            set_language,
            [lang_state, frame_state, corners_state, timeline_out, scorecard_out, evidence_detail, session_dd],
            [header_html, lang_toggle_btn]
            + [c for c, _ in HTML_TARGETS]
            + [c for c, _ in LABEL_TARGETS]
            + [c for c, _ in VALUE_TARGETS]
            + [c for c, _ in INFO_TARGETS]
            + [blade_model_path, chat_in, readiness_out, status]
            + [c for c, _, _ in PLACEHOLDER_TARGETS]
            + [overview_md]
            + [lang_state],
        )
    return demo


if __name__ == "__main__":
    app = build_app()
    webui_user = os.environ.get("WEBUI_USER")
    webui_password = os.environ.get("WEBUI_PASSWORD")
    if bool(webui_user) != bool(webui_password):
        raise RuntimeError("WEBUI_USER 与 WEBUI_PASSWORD 必须同时设置")
    app.launch(
        server_name=os.environ.get("WEBUI_HOST", "0.0.0.0"),
        server_port=int(os.environ.get("WEBUI_PORT", "7860")),
        show_error=True,
        auth=(webui_user, webui_password) if webui_user else None,
    )
