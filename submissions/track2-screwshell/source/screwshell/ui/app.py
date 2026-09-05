"""ScrewShell Gradio UI — one-stop investigation observatory (V3).

V3 rebuild of the observatory panel. See ``BUILD_OBSERVATORY_V3.md`` for the
full acceptance plan. The four high-level changes vs V2:

  1. **Three views** (概览 / 实时 / 流水 / 调优) via ``gr.Tabs`` — the old
     wall of text is分层 so a non-technical user reads four things in 10s.
  2. **Centralized thresholds** (``screwshell/ui/thresholds.py``) — every
     ⚠️ is judged in one place and MUST carry an "what to do" action line.
  3. **Trends + percentiles** — TTFT / KV-hit time-series (UI ring buffers)
     and p50/p95 replace the misleading mean that the long 30–172s tail broke.
  4. **Tuning transparency** (P4) — the governor card (honestly "未启用" on the
     UI path), A/B compare of two request windows, and config-version snapshots
     polled read-only from llama-server ``/props``.

Every number-formatting helper is a *pure function* that takes data and returns
a string / DataFrame, so the dashboard is unit-tested against fixtures without
launching Gradio or a model server. The four output sites (``dashboard_values``,
``respond`` yield, ``auto_refresh``, ``apply_lang``) are all derived from the
single ``DASH_NAMES`` ordering, so they can never drift out of sync (the V2
foot-gun the plan calls out in §1/P1).

Launch on remote:
  source /opt/venv/bin/activate
  python -m screwshell.ui.app --workspace /persistent/screwshell/demo_workspace
Then tunnel:  ssh -L 7860:localhost:7860 ...
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime
from typing import Optional

logger = logging.getLogger("screwshell.ui.app")

import gradio as gr
import pandas as pd

from screwshell.app import build_app
from screwshell.ui.analysis import (
    build_config_snapshot,
    compare_windows,
    compute_percentiles,
    percentile,
    rollback_command,
    run_ab_split,
    sample_count_ok,
    session_request_hierarchy,
    slice_events,
    split_ab_windows,
    _normalize_settings,
)
from screwshell.ui.thresholds import (
    OBS_THRESHOLDS,
    action_key,
    health_score,
    is_prompt_long,
    judge,
    warn_key,
)


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

I18N = {
    "zh": {
        "title": "# ScrewShell · 观测台\n**私有本地知识调查员** · MoL 核心：基础 Qwen3.6-27B + 可热切换 LoRA 专家 · AMD Radeon PRO W7900 / ROCm · 零远程 API 调用",
        "lang": "语言",
        "think": "深度思考（更慢，但推理更深）",
        "deep": "始终深度调查（关闭闲聊快速通道）",
        "chat_label": "调查对话",
        "msg_label": "向本地文档 / 代码 / 笔记提问",
        "msg_ph": "ROCm 迁移计划里的主要风险有哪些？请引用文档。",
        "send": "开始调查",
        "status_label": "当前状态",
        "idle": "就绪",
        "gpu_chart_title": "GPU：VRAM 占用% / 计算利用率%",
        "tps_chart_title": "解码速度（tok/s）",
        "ttft_chart_title": "首字延迟（ms）",
        "kv_chart_title": "KV 缓存命中率",
        "plan_label": "任务计划",
        "lora_label": "MoL：当前 LoRA 专家与切换记录",
        "gen_label": "推理吞吐",
        "tools_label": "工具调用",
        "ev_label": "证据卡片",
        "audit_label": "权限与审计日志",
        "gpu_label": "GPU 状态（rocm-smi）",
        # dynamic phases
        "thinking": "调查中…",
        "quick": "正在快速回复…",
        "planning": "正在规划调查步骤…",
        "finalizing": "正在汇总最终答案…",
        "step": "正在执行第 {i}/{n} 步…",
        # empty-state placeholders
        "no_plan": "（当前没有进行中的任务）",
        "no_tools": "（暂无工具调用）",
        "no_audit": "（审计日志为空）",
        "no_gen": "（暂无生成记录）",
        "base": "基础模型（Qwen3.6-27B）",
        "err": "（错误：没有返回结果）",
        "obs_label": "观测面板（中继全局视角）",
        "obs_summary_label": "汇总（全部前端经中继的请求）",
        "obs_recent_label": "最近请求（活动流）",
        "obs_refresh": "刷新观测",
        "obs_offline": "（观测未连接：中继未设 OBSERV_DIR，或本 UI 未走中继）",
        "ext_no_data": "（外部前端无数据 — 见右侧活动流）",
        # ---- 方向 B: step timeline ----
        "tl_none": "（暂无调查流程）",
        "tl_task": "任务: {task}",
        "tl_planning": "规划中…",
        "tl_finalizing": "正在汇总最终答案…",
        "tl_step": "步骤 {i}/{n}: {desc}",
        "tl_step_run": "步骤 {i}/{n}: {desc}  [技能:{skill}]",
        "tl_done": "✓ {desc}",
        # ---- V3 view tabs ----
        "tab_overview": "概览",
        "tab_live": "实时",
        "tab_stream": "流水",
        "tab_tuning": "调优",
        # ---- auto-tune panel (tune-loop plan, Todo 7) ----
        "tab_autotune": "一键调优",
        "tune_preset": "调优目标",
        "tune_preset_speed": "更快（提吞吐）",
        "tune_preset_vram": "省显存",
        "tune_preset_ctx": "更大上下文",
        "tune_preset_balance": "平衡（保持现状）",
        "tune_start": "一键调优",
        "tune_stop": "停止调优",
        "tune_status_idle": "空闲",
        "tune_status_running": "调优中…",
        "tune_status_done": "调优完成",
        "tune_status_abort": "调优中止（含失败升级）",
        "tune_rolling_back": "正在回滚上一版参数…",
        "tune_converged": "已收敛（指标不再改善）",
        "tune_progress": "调优进度",
        # ---- V3 health banner ----
        "health_ok": "✅ 服务正常",
        "health_warn": "⚠️ 需关注",
        "health_alert": "🛑 异常",
        "health_see_cards": "看哪张卡：{which}",
        # ---- V3 metric cards ----
        "card_ok_rate": "成功率",
        "card_ttft": "首字延迟",
        "card_ttft_p95": "本次会话首字延迟 p95",
        "card_tps": "解码速度",
        "card_kv": "KV 命中",
        "card_experts": "专家分布",
        "card_session": "当前操作会话",
        "card_low_confidence": "样本不足，p95/p99 仅供参考（非告警门槛）",
        "card_server": "全局(server)",
        "card_errors": "错误",
        "experts_none": "（无分布数据）",
        "server_none": "（无 server 计数）",
        "errors_none": "（无错误）",
        # ---- V3 percentiles ----
        "pct_title": "首字延迟分位数（n={n}）",
        "pct_sample_low": "样本不足（n={n}），暂不展示分位数",
        "pct_low_confidence": "样本不足（n={n}），p99 不可信，仅展示 p50/p95 参考",
        # ---- V3 causal hint ----
        "causal_title": "🔎 为什么这次慢？",
        "causal_none": "（首字延迟正常，无需解释）",
        # ---- V3 trend anomaly ----
        "trend_anomaly_title": "📈 趋势异常",
        "trend_rising": "⚠️ 首字延迟近 10 分钟持续上升",
        "trend_inflating": "⚠️ 输入 token 较基线膨胀 >1.3×",
        "trend_none": "（趋势平稳）",
        # ---- V3 governor card ----
        "gov_disabled": "🤖 自动调优未启用",
        "gov_disabled_hint": "当前 UI 路径未挂载 governor（避免自动降上下文/关思考影响体验）。启用需独立计划并重跑真机 A/B 验收。以下为「如果启用」会做什么：",
        "gov_enabled_title": "🤖 自动调优（governor）",
        "gov_enabled_status": "启用中",
        "gov_mode": "模式",
        "gov_mode_enabled": "启用（roomy/tight/auto 由运行层决定）",
        "gov_actions": "最近动作",
        "gov_alerts": "最近告警",
        "gov_stable": "稳定性",
        "gov_stable_ok": "稳定",
        "gov_stable_bad": "⚠️ 反复升降档（调优可能过激）",
        "gov_none": "（暂无动作/告警）",
        # ---- V3 A/B compare ----
        "ab_title": "⚖️ A/B 对比（主指标：首字延迟 TTFT）",
        "ab_mode": "窗口切分方式",
        "ab_mode_half": "按时间对半分",
        "ab_mode_run": "按 run_id 变化为界",
        "ab_mode_minutes": "按分钟窗口（A 在前 / B 在后）",
        "ab_window_min": "窗口长度（分钟）",
        "ab_run": "运行对比",
        "ab_set_baseline": "将 A 设为基线",
        "ab_baseline": "基线",
        "ab_sample_low": "样本不足（A n={na} / B n={nb}），暂不判胜负（实验纪律 T4）",
        "ab_verdict_a": "A（改动前）胜",
        "ab_verdict_b": "B（改动后）胜",
        "ab_verdict_tie": "无明显差异",
        "ab_metric_ttft": "首字延迟",
        "ab_metric_tps": "解码速度",
        "ab_metric_kv": "KV 命中",
        "ab_metric_ok": "成功率",
        "ab_diff_note": "差异（含混杂因素，非因果证明）",
        "ab_baseline_set": "基线已设为：{desc}",
        "ab_no_data": "（暂无请求数据，无法对比；真机运行后自动出现）",
        # ---- V3 A/B compare (time-only) ----
        "ab_single_value": "时间窗口只有一个区段，无法切分（实验纪律：不对单一取值编造 A/B 胜负）",
        "ab_time_label": "按时间窗口对比（A 在前 / B 在后）",
        # ---- V3 config versions ----
        "cfg_title": "🗂 配置版本（只读快照，零存储）",
        "cfg_none": "（暂无配置快照：llama-server 无 /props 或不可达）",
        "cfg_rollback": "回滚命令（复制后由人/运行层执行）",
        "cfg_diff": "变更",
        "cfg_no_diff": "（首个版本，无对比）",
        # ---- V3 stream filter ----
        "filter_entry": "入口筛选",
        "filter_entry_all": "全部",
        "filter_expert": "专家筛选",
        "filter_expert_all": "全部",
        "filter_ok": "成败",
        "filter_ok_all": "全部",
        "filter_ok_ok": "仅成功",
        "filter_ok_fail": "仅失败",
        # ---- 方向 B: session->request drill-down ----
        "drill_empty": "（暂无数据，无法钻取）",
        "drill_all_sessions": "全部操作会话（父级）：",
        "drill_session": "操作会话",
        "drill_request": "单次调用",
        "drill_no_session": "(no-session)",
        "drill_n_requests": "n 次请求={n}",
        "drill_sample_low": "（样本不足，不展示细分）",
        "drill_ok": "成功",
        "drill_fail": "失败",
        "drill_req_id": "request_id",
        "drill_run_id": "run_id",
        # ---- V3 threshold action texts (§2.5, must pair with every ⚠️) ----
        "thr_ttft_warn": "首字延迟偏慢",
        "thr_ttft_action": "慢的常见原因：资料太长 / 刚切过专家 / 在排队（见下方原因与建议）",
        "thr_tps_warn": "生成偏慢",
        "thr_tps_action": "生成变慢，常见原因：显存不足或正跑超长上下文",
        "thr_kv_warn": "缓存续接不足",
        "thr_kv_action": "缓存没续上，常见原因：频繁切专家 / 会话过长（建议开新会话）",
        "thr_ok_warn": "成功率偏低",
        "thr_ok_action": "成功率偏低：检查上游服务是否稳定，重试或看错误卡片",
        "thr_switch_warn": "切换耗时异常",
        "thr_switch_action": "切换超过 1s，检查 LoRA 加载或显存压力",
        "thr_prompt_warn": "会话过长",
        "thr_prompt_action": "接近上下文上限，建议开新会话以恢复速度",
    },
    "en": {
        "title": "# ScrewShell · Observatory\n**Private local knowledge investigator** · MoL core: base Qwen3.6-27B + hot-swappable LoRA experts · AMD Radeon PRO W7900 / ROCm · zero remote API calls",
        "lang": "Language",
        "think": "Deep thinking (slower, deeper reasoning)",
        "deep": "Always deep-investigate (disable chat fast path)",
        "chat_label": "Investigation chat",
        "msg_label": "Ask your local docs / code / notes",
        "msg_ph": "What are the main risks in the ROCm migration plan? Cite the docs.",
        "send": "Investigate",
        "status_label": "Current status",
        "idle": "ready",
        "gpu_chart_title": "GPU: VRAM% / compute util%",
        "tps_chart_title": "Decode speed (tok/s)",
        "ttft_chart_title": "First-token latency (ms)",
        "kv_chart_title": "KV cache hit rate",
        "plan_label": "Task plan",
        "lora_label": "MoL: active LoRA expert & switch log",
        "gen_label": "Throughput",
        "tools_label": "Tool calls",
        "ev_label": "Evidence cards",
        "audit_label": "Permission & audit log",
        "gpu_label": "GPU status (rocm-smi)",
        "thinking": "Investigating…",
        "quick": "Replying quickly…",
        "planning": "Planning investigation steps…",
        "finalizing": "Synthesizing final answer…",
        "step": "Running step {i}/{n}…",
        "no_plan": "(no task in progress)",
        "no_tools": "(no tool calls yet)",
        "no_audit": "(audit log empty)",
        "no_gen": "(no generations yet)",
        "base": "base model (Qwen3.6-27B)",
        "err": "(error: no result returned)",
        "obs_label": "Observability (relay global view)",
        "obs_summary_label": "Summary (all requests via relay)",
        "obs_recent_label": "Recent requests (activity stream)",
        "obs_refresh": "Refresh observ.",
        "obs_offline": "(observability offline: relay has no OBSERV_DIR, or UI not via relay)",
        "ext_no_data": "(no data from external frontends — see activity stream)",
        # ---- 方向 B: step timeline ----
        "tl_none": "(no investigation in progress)",
        "tl_task": "Task: {task}",
        "tl_planning": "Planning…",
        "tl_finalizing": "Finalizing…",
        "tl_step": "Step {i}/{n}: {desc}",
        "tl_step_run": "Step {i}/{n}: {desc}  [skill:{skill}]",
        "tl_done": "✓ {desc}",
        "tab_overview": "Overview",
        "tab_live": "Live",
        "tab_stream": "Stream",
        "tab_tuning": "Tuning",
        "tab_autotune": "One-Click Tune",
        "tune_preset": "Tune goal",
        "tune_preset_speed": "Faster (more throughput)",
        "tune_preset_vram": "Save VRAM",
        "tune_preset_ctx": "Larger context",
        "tune_preset_balance": "Balanced (keep as-is)",
        "tune_start": "Auto-Tune",
        "tune_stop": "Stop Tuning",
        "tune_status_idle": "Idle",
        "tune_status_running": "Tuning…",
        "tune_status_done": "Tuning done",
        "tune_status_abort": "Tuning aborted (with fail-escalation)",
        "tune_rolling_back": "Rolling back to last-good params…",
        "tune_converged": "Converged (no further improvement)",
        "tune_progress": "Tuning progress",
        "health_ok": "✅ Healthy",
        "health_warn": "⚠️ Needs attention",
        "health_alert": "🛑 Critical",
        "health_see_cards": "Check card(s): {which}",
        "card_ok_rate": "Success rate",
        "card_ttft": "First-token latency",
        "card_ttft_p95": "Session TTFT p95",
        "card_tps": "Decode speed",
        "card_kv": "KV hit",
        "card_experts": "Expert split",
        "card_session": "Current operational session",
        "card_low_confidence": "Low sample: p95/p99 shown for reference only (not an alert threshold)",
        "card_server": "Server-wide",
        "card_errors": "Errors",
        "experts_none": "(no split data)",
        "server_none": "(no server counters)",
        "errors_none": "(no errors)",
        "pct_title": "TTFT percentiles (n={n})",
        "pct_sample_low": "Sample too small (n={n}); percentiles hidden",
        "pct_low_confidence": "Low sample (n={n}); p99 untrusted, showing p50/p95 only",
        "causal_title": "🔎 Why was this slow?",
        "causal_none": "(first-token latency is normal; nothing to explain)",
        "trend_anomaly_title": "📈 Trend anomalies",
        "trend_rising": "⚠️ TTFT has been rising for ~10 min",
        "trend_inflating": "⚠️ input tokens >1.3× baseline",
        "trend_none": "(trends stable)",
        "gov_disabled": "🤖 Auto-tuning disabled",
        "gov_disabled_hint": "The UI path does not mount a governor (to avoid auto ctx-shrink / thinking-off hurting UX). Enabling needs a separate plan + real-machine A/B. Below is what it *would* do:",
        "gov_enabled_title": "🤖 Auto-tuning (governor)",
        "gov_enabled_status": "enabled",
        "gov_mode": "Mode",
        "gov_mode_enabled": "enabled (roomy/tight/auto decided by runtime)",
        "gov_actions": "Recent actions",
        "gov_alerts": "Recent alerts",
        "gov_stable": "Stability",
        "gov_stable_ok": "stable",
        "gov_stable_bad": "⚠️ oscillating up/down (tuning may be too aggressive)",
        "gov_none": "(no actions/alerts yet)",
        "ab_title": "⚖️ A/B compare (primary metric: TTFT)",
        "ab_mode": "Window split",
        "ab_mode_half": "split by time (half/half)",
        "ab_mode_run": "split at run_id change",
        "ab_mode_minutes": "by minute window (A before / B after)",
        "ab_window_min": "Window length (min)",
        "ab_run": "Run compare",
        "ab_set_baseline": "Set A as baseline",
        "ab_baseline": "Baseline",
        "ab_sample_low": "Sample too small (A n={na} / B n={nb}); no verdict (discipline T4)",
        "ab_verdict_a": "A (before) wins",
        "ab_verdict_b": "B (after) wins",
        "ab_verdict_tie": "no significant difference",
        "ab_metric_ttft": "TTFT",
        "ab_metric_tps": "decode",
        "ab_metric_kv": "KV hit",
        "ab_metric_ok": "success",
        "ab_diff_note": "difference (with confounders, not causal proof)",
        "ab_baseline_set": "Baseline set to: {desc}",
        "ab_no_data": "(no request data to compare; appears after real runs)",
        # ---- V3 A/B compare (time-only) ----
        "ab_single_value": "the time window has a single segment; cannot split (discipline: never fabricate an A/B verdict for one value)",
        "ab_time_label": "compare by time window (A before / B after)",
        "cfg_title": "🗂 Config versions (read-only snapshot, no storage)",
        "cfg_none": "(no config snapshot: llama-server has no /props or unreachable)",
        "cfg_rollback": "Rollback command (copy, then apply by human/runtime)",
        "cfg_diff": "change",
        "cfg_no_diff": "(first version, nothing to diff)",
        "filter_entry": "Entry filter",
        "filter_entry_all": "All",
        "filter_expert": "Expert filter",
        "filter_expert_all": "All",
        "filter_ok": "Pass/fail",
        "filter_ok_all": "All",
        "filter_ok_ok": "Only success",
        "filter_ok_fail": "Only fail",
        # ---- 方向 B: session->request drill-down ----
        "drill_empty": "(no data to drill down)",
        "drill_all_sessions": "All operation sessions (parent):",
        "drill_session": "Operation session",
        "drill_request": "Single call",
        "drill_no_session": "(no-session)",
        "drill_n_requests": "n requests={n}",
        "drill_sample_low": "(sample too small; not broken down)",
        "drill_ok": "ok",
        "drill_fail": "fail",
        "drill_req_id": "request_id",
        "drill_run_id": "run_id",
        "thr_ttft_warn": "TTFT slow",
        "thr_ttft_action": "Common causes: long context / just switched expert / queued (see reason & advice below)",
        "thr_tps_warn": "Decode slow",
        "thr_tps_action": "Decode slowed: likely low VRAM headroom or a very long context",
        "thr_kv_warn": "Cache not resumed",
        "thr_kv_action": "Cache not resumed: frequent expert switches / long session (open a new session)",
        "thr_ok_warn": "Success rate low",
        "thr_ok_action": "Success rate low: check upstream stability, retry, or see error cards",
        "thr_switch_warn": "Switch too slow",
        "thr_switch_action": "Switch >1s: check LoRA load or VRAM pressure",
        "thr_prompt_warn": "Session too long",
        "thr_prompt_action": "Near context limit: open a new session to restore speed",
    },
}


LANG_CHOICES = [("中文", "zh"), ("English", "en")]
_LANG_ALIASES = {"中文": "zh", "English": "en"}


def norm_lang(lang: str) -> str:
    if lang in I18N:
        return lang
    return _LANG_ALIASES.get(lang, "zh")


def T(lang: str, key: str, **kw) -> str:
    try:
        s = I18N[norm_lang(lang)][key]
    except KeyError:
        # i18n must never crash the UI (§2.5): fall back to zh and log.
        logger.warning("missing i18n key: %s", key)
        fallback = I18N["zh"].get(key, key)
        return fallback.format(**kw) if kw else fallback
    try:
        return s.format(**kw) if kw else s
    except (KeyError, IndexError):
        # i18n must never crash the UI (§2.5): fall back to zh and log.
        logger.warning("missing i18n key: %s", key)
        fallback = I18N["zh"].get(key, key)
        return fallback.format(**kw) if kw else fallback


def phase_text(lang: str, key: str, i: int = 0, n: int = 0) -> str:
    if key == "step":
        return T(lang, "step", i=i, n=n)
    return T(lang, key)


# Color dual-channel (§2.10): symbol + color, color-blind friendly.
_COLORS = {"ok": "#2e7d32", "warn": "#b26a00", "alert": "#c62828"}


def _span(text: str, level: str) -> str:
    color = _COLORS.get(level, _COLORS["ok"])
    return f'<span style="color:{color}">{text}</span>'


def _ok_warn(v: bool, lang: str = "zh") -> str:
    return _span("✓", "ok") if v else _span("⚠️", "warn")


# ---------------------------------------------------------------------------
# Observability poller — polls the relay (which owns the global RequestEvent
# store) for a cross-frontend view. Falls back to "offline" silently when the
# relay is not reachable / OBSERV_DIR not set. Also feeds UI-side ring buffers
# for the GPU / throughput / TTFT / KV time-series charts, and a read-only
# config-version snapshot polled from llama-server /props.
# ---------------------------------------------------------------------------

_RELAY_BASE = os.getenv("MOL_LLAMACPP_URL", "http://127.0.0.1:18090").rstrip("/")
# Relay's observ endpoints are gated by RELAY_TRUST_TOKEN (when set). The UI
# runs on the same host and carries the same token, so present it as the
# X-Relay-Token header; when the token is unset (legacy loopback), the header
# is omitted and the relay serves observ read-only.
_RELAY_TOKEN = os.getenv("RELAY_TRUST_TOKEN", "")
_obs_state = {"summary": None, "recent": [], "gpu": None, "health": None,
              "slots": None, "expert": None, "llama_metrics": None,
              "props": None}

# Ring buffers for the time-series charts (≈6 min @ 2s cadence).
_GPU_HIST: deque = deque(maxlen=180)   # {"ts", "vram_pct", "util_pct"}
_TPS_HIST: deque = deque(maxlen=180)   # {"ts", "tps"}
_TTFT_HIST: deque = deque(maxlen=180)  # {"ts", "ttft_ms"}
_KV_HIST: deque = deque(maxlen=180)    # {"ts", "kv_hit_rate"}

# Governor + config-version state (P4).
_GOV_EVENTS: list[dict] = []           # {"ts", "kind", "reason"}
_CONFIG_VERSIONS: deque = deque(maxlen=20)  # config snapshots (dicts)
_CONFIG_BASELINE: Optional[str] = None  # version id marked as baseline
_AB_RESULT: Optional[dict] = None       # last A/B compare result (for the UI)
_AB_BASELINE_DESC: Optional[str] = None
_AB_DIM: Optional[str] = "time"          # A/B now always splits by time window
# 方向 B drill-down selection (persisted so the 2s auto-refresh keeps the view).
_DRILL_SESSION: Optional[str] = None       # operation session id, None = all
_DRILL_REQUEST: Optional[str] = None       # request id, None = session-level
_CUR_LANG: str = "zh"

# 方向 B: step-timeline helpers. Keep the running step marked "done" before a
# new step / planning / finalizing marker starts, and bound the list size.
_TIMELINE_MAX = 50


def _timeline_close_running() -> None:
    for rec in reversed(_UI_STATE["timeline"]):
        if rec.get("kind") == "step" and rec.get("status") == "running":
            rec["status"] = "done"
            return


def _timeline_trim() -> None:
    tl = _UI_STATE["timeline"]
    if len(tl) > _TIMELINE_MAX:
        del tl[:len(tl) - _TIMELINE_MAX]

_STREAM_FILTER: dict = {"entry": "all", "expert": "all", "ok": "all"}

# Shared UI-state lifted to module scope so the 2s timer can read phase /
# elapsed without coupling to the respond() generator.
_UI_STATE = {
    "plan": "", "lora": [], "tools": [], "gens": [],
    "phase": "idle", "phase_i": 0, "phase_n": 0, "start_ts": 0.0,
    "thinking": "",
    "timeline": [],
}


def _obs_headers() -> dict:
    return {"X-Relay-Token": _RELAY_TOKEN} if _RELAY_TOKEN else {}


def _obs_get(path: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(_RELAY_BASE + path,
                                     headers=_obs_headers())
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _tune_post(path: str, payload: dict) -> Optional[dict]:
    """POST to a relay tune endpoint (urllib, reuses the observ auth header).

    Module-level so it is unit-testable without constructing the whole UI; the
    auto-tune handlers (inside make_ui) call this.
    """
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            _RELAY_BASE + path, data=data,
            headers={**_obs_headers(), "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"error": str(e), "status_code": e.code}
    except Exception:
        return None


def _poll_observ_once() -> None:
    # P3/P4: request a large window so percentiles + A/B have enough samples.
    ev = _obs_get("/v1/observ/events?n=200")
    if ev is not None:
        _obs_state["recent"] = ev.get("events", [])
    # Derive the CURRENT operational session id from the freshest event, then
    # pull a SESSION-SCOPED summary (exclude benchmark traffic) so the health
    # banner judges this conversation's p95, not the legacy global mean (§5.3).
    # Falls back to the global summary when the store has no events yet.
    recent = _obs_state.get("recent") or []
    cur_session = None
    # recent is newest-first (relay returns reversed ring); the CURRENT
    # operational session is the freshest event's session id.
    for e in recent:
        sid = e.get("operational_session_id")
        if sid:
            cur_session = sid
            break
    if cur_session:
        sess = _obs_get(
            f"/v1/observ/summary?session_id={cur_session}"
            f"&exclude_benchmark=true")
        if sess is not None:
            _obs_state["session_summary"] = sess
    # Global summary retained for drill-down / historical view (back-compat).
    g = _obs_get("/v1/observ/summary")
    if g is not None:
        _obs_state["summary"] = g
    gh = _obs_get("/v1/observ/gpu_history?n=180")
    if gh is not None and gh.get("samples"):
        _GPU_HIST.clear()
        for s in gh["samples"]:
            if isinstance(s.get("ts"), (int, float)):
                vram_pct = None
                if (isinstance(s.get("vram_used_b"), (int, float))
                        and isinstance(s.get("vram_total_b"), (int, float))
                        and s.get("vram_total_b")):
                    vram_pct = s["vram_used_b"] / s["vram_total_b"] * 100
                _GPU_HIST.append({
                    "ts": s["ts"],
                    "vram_pct": vram_pct,
                    "util_pct": s.get("use_pct"),
                })
    else:
        g = _obs_get("/v1/observ/gpu")
        if g is not None:
            _obs_state["gpu"] = g
            if g.get("ok"):
                used, total = g.get("used_b"), g.get("total_b")
                vram_pct = None
                if isinstance(used, int) and isinstance(total, int) and total:
                    vram_pct = used / total * 100
                util_pct = g.get("use_pct")
                if vram_pct is not None or isinstance(util_pct, (int, float)):
                    _GPU_HIST.append({
                        "ts": time.time(),
                        "vram_pct": vram_pct,
                        "util_pct": util_pct,
                    })
    h = _obs_get("/health")
    if h is not None:
        _obs_state["health"] = h
    _obs_state["slots"] = _obs_get("/v1/observ/slots")
    _obs_state["expert"] = _obs_get("/v1/observ/expert")
    _obs_state["llama_metrics"] = _obs_get("/v1/observ/llama_metrics")
    _obs_state["props"] = _obs_get("/v1/observ/props")
    # Throughput trace: freshest per-request decode_tps.
    for e in reversed(_obs_state.get("recent") or []):
        tps = e.get("decode_tps")
        if isinstance(tps, (int, float)):
            ts = e.get("ts") or time.time()
            if not _TPS_HIST or ts > _TPS_HIST[-1]["ts"]:
                _TPS_HIST.append({"ts": ts, "tps": tps})
            break
    # TTFT / KV trend rings: every recent request contributes a point.
    for e in reversed(_obs_state.get("recent") or []):
        ttft = e.get("ttft_ms")
        if isinstance(ttft, (int, float)):
            ts = e.get("ts") or time.time()
            if not _TTFT_HIST or ts > _TTFT_HIST[-1]["ts"]:
                _TTFT_HIST.append({"ts": ts, "ttft_ms": ttft})
        kv = e.get("kv_hit_rate")
        if isinstance(kv, (int, float)):
            ts = e.get("ts") or time.time()
            if not _KV_HIST or ts > _KV_HIST[-1]["ts"]:
                _KV_HIST.append({"ts": ts, "kv_hit_rate": kv})
    # Config-version snapshot from /props (read-only, zero storage).
    _maybe_record_config_version()


def _maybe_record_config_version() -> None:
    props = _obs_state.get("props")
    if not isinstance(props, dict) or not props:
        return
    snap = build_config_snapshot(props, ts=time.time())
    if _CONFIG_VERSIONS and _CONFIG_VERSIONS[-1].get("vid") == snap["vid"]:
        return  # unchanged -> do not spam versions
    _CONFIG_VERSIONS.append(snap)


def _start_observ_poller() -> None:
    def loop():
        while True:
            _poll_observ_once()
            time.sleep(2)
    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------------------
# Pure computation helpers live in screwshell.ui.analysis (gradio-free,
# unit-tested). The formatting helpers below (data in -> string/DataFrame out)
# stay here because they need i18n / module globals.
# ---------------------------------------------------------------------------

def causal_hint(summary: dict, slots: Optional[list], recent: list[dict],
                lang: str) -> str:
    """§2.6 — when TTFT is slow, output the most likely cause + advice.

    Priority: 会话过长 > 资料过长 > 切换密集. Returns "" when TTFT is healthy.
    """
    ttft = summary.get("avg_ttft_ms") if isinstance(summary, dict) else None
    if not isinstance(ttft, (int, float)) or ttft < 5000:
        return ""
    zh = lang == "zh"
    # 1) 会话过长: any recent request with prompt_tokens over the warn threshold
    for e in recent or []:
        if is_prompt_long(e.get("prompt_tokens")):
            return (f"{T(lang,'causal_title')}\n可能原因：{T(lang,'thr_prompt_warn')}"
                    f"｜建议：{T(lang,'thr_prompt_action')}")
    # 2) 资料过长: a busy slot with a large prompt still being processed
    if isinstance(slots, list):
        for s in slots:
            n = s.get("n_prompt_tokens") or 0
            if isinstance(n, (int, float)) and n > 20000:
                return (f"{T(lang,'causal_title')}\n可能原因：资料过长"
                        f"（{n} token）｜建议："
                        f"{'缩短提问范围或开新会话' if zh else 'narrow the question or start a new session'}")
    # 3) 切换密集: >=3 switches in the recent window
    switches = sum(1 for e in (recent or []) if e.get("switched"))
    if switches >= 3:
        return (f"{T(lang,'causal_title')}\n可能原因：刚频繁切换专家"
                f"（{switches} 次）｜建议："
                f"{'缓存反复失效，稍等稳定后再问' if zh else 'cache repeatedly invalidated; wait for it to settle'}")
    return (f"{T(lang,'causal_title')}\n可能原因：排队或长 prompt prefill"
            f"｜建议：{T(lang,'thr_ttft_action')}")


def _metric_card(label: str, value: str, ok: bool, action: str,
                 lang: str) -> str:
    sym = _ok_warn(ok, lang)
    line = f"- {sym} **{label}**：{value}"
    if not ok and action:
        line += f"  \n  ↳ {action}"
    return line


def fmt_metric_cards(summary: dict, lang: str) -> str:
    """V3 §2.2 — four number cards, each ✓/⚠️ + (if ⚠️) an action line."""
    if not isinstance(summary, dict):
        return T(lang, "obs_offline")
    if not summary.get("count"):
        return "（0 请求）" if lang == "zh" else "(0 requests)"
    zh = lang == "zh"
    ba = summary.get("by_adapter") or {}
    ba_str = "  ".join(f"{k}:{v}" for k, v in sorted(ba.items(),
                                                     key=lambda kv: -kv[1]))
    ok_rate = summary.get("ok_rate")
    ttft = summary.get("avg_ttft_ms")
    tps = summary.get("avg_decode_tps")
    kv = summary.get("kv_hit_rate")
    lines = []
    # success rate
    ok_ok = isinstance(ok_rate, (int, float)) and judge("ok_rate", ok_rate)
    lines.append(_metric_card(
        T(lang, "card_ok_rate"),
        f"{ok_rate*100:.0f}%" if isinstance(ok_rate, (int, float)) else "n/a",
        ok_ok,
        T(lang, action_key("ok_rate")) if not ok_ok else "",
        lang))
    # ttft — session-scoped p95 (the health judge), with p50 fallback label.
    # The legacy avg_ttft_ms is shown only as a secondary "global" note below.
    ttft_val = summary.get("ttft_p95")
    ttft_label = T(lang, "card_ttft_p95")
    if not isinstance(ttft_val, (int, float)):
        ttft_val = ttft  # fall back to global mean when no session p95
        ttft_label = T(lang, "card_ttft")
    ttft_ok = judge("ttft_ms", ttft_val)
    lines.append(_metric_card(
        ttft_label,
        f"{ttft_val:.0f}ms" if isinstance(ttft_val, (int, float)) else "n/a",
        ttft_ok, T(lang, action_key("ttft_ms")), lang))
    # decode tps
    tps_ok = judge("decode_tps", tps)
    lines.append(_metric_card(
        T(lang, "card_tps"),
        f"{tps:.1f} tok/s" if isinstance(tps, (int, float)) else "n/a",
        tps_ok, T(lang, action_key("decode_tps")), lang))
    # kv hit
    kv_ok = judge("kv_hit", kv)
    lines.append(_metric_card(
        T(lang, "card_kv"),
        f"{kv*100:.0f}%" if isinstance(kv, (int, float)) else "n/a",
        kv_ok, T(lang, action_key("kv_hit")), lang))
    # expert split
    lines.append(f"- **{T(lang,'card_experts')}**：{ba_str or T(lang,'experts_none')}")
    # session-scoped observability (§5): which session we are judging + its
    # boundary/warm split + low-confidence flag (T4 discipline).
    sess = summary.get("operational_session_id")
    if sess:
        bc = summary.get("boundary_count") or 0
        wc = summary.get("warm_count") or 0
        lines.append(f"- **{T(lang,'card_session')}**：`{sess[:8]}` "
                     f"· boundary {bc} / warm {wc}")
    if summary.get("low_confidence"):
        lines.append(f"- ⚠️ {T(lang,'card_low_confidence')}")
    # server-wide counters (R2)
    lm = _obs_state.get("llama_metrics") or {}
    c = lm.get("counters") or {}
    if c.get("prompt_tokens_total") is not None:
        total_tok = (int(c.get("prompt_tokens_total") or 0)
                     + int(c.get("tokens_predicted_total") or 0))
        lines.append(f"- **{T(lang,'card_server')}**：KV命中+"
                     f"{int(c.get('cache_hits_total') or 0)} 总token {total_tok}")
    else:
        lines.append(f"- **{T(lang,'card_server')}**：{T(lang,'server_none')}")
    # errors
    if summary.get("errors"):
        lines.append(f"- **{T(lang,'card_errors')}**："
                     + "; ".join(str(e) for e in summary["errors"][:3]))
    else:
        lines.append(f"- **{T(lang,'card_errors')}**：{T(lang,'errors_none')}")
    return "\n".join(lines)


def fmt_health_banner(summary: dict, lang: str) -> str:
    """§2.10 — synthesize the top-level 正常/需关注/异常 banner."""
    level, which = health_score(summary if isinstance(summary, dict) else {})
    if level == "ok":
        return _span(T(lang, "health_ok"), "ok")
    label = T(lang, "health_warn") if level == "warn" else T(lang, "health_alert")
    span = _span(label, "warn" if level == "warn" else "alert")
    detail = T(lang, "health_see_cards", which=", ".join(which))
    return f"{span}\n\n{detail}"


def fmt_percentiles(recent: list[dict], lang: str, summary: dict = None) -> str:
    """§2.4 / §5.3 — TTFT p50/p95/p99 of the CURRENT operational session.

    Prefers the session-scoped ``summary`` (carries ttft_p50/p95/p99 computed by
    the relay over the filtered window). Falls back to computing from ``recent``
    when no summary is supplied. Never fabricates: a too-small sample yields a
    "low confidence" line instead of a fake p99.
    """
    if isinstance(summary, dict) and isinstance(summary.get("ttft_p95"),
                                                 (int, float)):
        n = summary.get("count") or 0
        p50 = summary.get("ttft_p50")
        p95 = summary.get("ttft_p95")
        p99 = summary.get("ttft_p99")
        if summary.get("low_confidence"):
            return T(lang, "pct_low_confidence", n=n)
        title = T(lang, "pct_title", n=n)
        def _f(v):
            return f"{v/1000:.1f}s" if (isinstance(v, (int, float)) and v >= 1000) \
                else (f"{v:.0f}ms" if isinstance(v, (int, float)) else "n/a")
        return f"{title}\n- p50 {_f(p50)} · p95 {_f(p95)} · p99 {_f(p99)}"
    # Fallback: compute from raw recent events (global window).
    p = compute_percentiles(recent or [])
    if p["n"] == 0:
        return T(lang, "pct_sample_low", n=0)
    if p["n"] < 8:
        return T(lang, "pct_sample_low", n=p["n"])
    title = T(lang, "pct_title", n=p["n"])
    p50 = f"{p['p50']/1000:.1f}s" if p["p50"] >= 1000 else f"{p['p50']:.0f}ms"
    p95 = f"{p['p95']/1000:.1f}s" if p["p95"] >= 1000 else f"{p['p95']:.0f}ms"
    return f"{title}\n- p50 {p50} · p95 {p95}"


# ---- dimension breakdown (Todo 3) ----
def _aggregate_session(events: list[dict], lang: str) -> dict:
    """Aggregate ttft/decode/kv over a list of request events (honest: means
    only; never fabricates a value for missing fields)."""
    ttfts = [e["ttft_ms"] for e in events if isinstance(e.get("ttft_ms"), (int, float))]
    tps = [e["decode_tps"] for e in events if isinstance(e.get("decode_tps"), (int, float))]
    kv = [e["kv_hit_rate"] for e in events if isinstance(e.get("kv_hit_rate"), (int, float))]
    return {
        "n": len(events),
        "ttft": (sum(ttfts) / len(ttfts)) if ttfts else None,
        "tps": (sum(tps) / len(tps)) if tps else None,
        "kv": (sum(kv) / len(kv)) if kv else None,
    }


def _fmt_metric(v, scale_ms: bool = False) -> str:
    if v is None:
        return "n/a"
    if scale_ms and v >= 1000:
        return f"{v/1000:.1f}s"
    if scale_ms:
        return f"{v:.0f}ms"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def fmt_session_request_drilldown(events: list[dict], session: Optional[str],
                                   request: Optional[str], lang: str) -> str:
    """方向 B — strict parent-child drill: operation session -> request.

    Renders into the Overview `percentiles` slot (reused to keep DASH_NAMES at
    20). Three zoom levels:
      * no session selected -> list every session with request count + aggregate;
      * session selected, no request -> list that session's requests (child rows);
      * both selected -> single request full detail.
    Honest-output: aggregates over <16 events show a sample-low note, never a
    fabricated verdict. Carries NO fabricated numbers.
    """
    evs = [e for e in (events or []) if isinstance(e, dict)]
    zh = lang == "zh"
    if not evs:
        return T(lang, "drill_empty")
    hierarchy = session_request_hierarchy(evs)
    # scope header
    if session is None:
        head = T(lang, "drill_all_sessions")
    elif request is None:
        head = T(lang, "drill_session") + f": {session}"
    else:
        head = (T(lang, "drill_session") + f": {session} · "
                + T(lang, "drill_request") + f": {request}")
    lines = [head]

    if session is None:
        # --- parent level: all sessions ---
        for sid in sorted(hierarchy.keys()):
            items = hierarchy[sid]
            agg = _aggregate_session(items, lang)
            label = sid if sid != "(no-session)" else T(lang, "drill_no_session")
            lines.append(f"- {label} ({T(lang, 'drill_n_requests', n=len(items))}"
                         f" · TTFT {_fmt_metric(agg['ttft'], True)}"
                         f" · TPS {_fmt_metric(agg['tps'])}"
                         f" · KV {_fmt_metric(agg['kv'])})")
            if not sample_count_ok(len(items)):
                lines.append(f"  {T(lang, 'drill_sample_low')}")
        return "\n".join(lines)

    items = hierarchy.get(session, [])
    if not items:
        return head + "\n" + T(lang, "drill_empty")

    if request is None:
        # --- child level: session's requests ---
        for e in sorted(items, key=lambda e: e.get("ts") or 0):
            rid = e.get("request_id") or "?"
            agg = _aggregate_session([e], lang)
            ok = T(lang, "drill_ok") if e.get("ok") else T(lang, "drill_fail")
            lines.append(
                f"- {rid} · run_id={e.get('run_id', '?')} · {ok}"
                f" · TTFT {_fmt_metric(e.get('ttft_ms'), True)}"
                f" · TPS {_fmt_metric(e.get('decode_tps'))}"
                f" · KV {_fmt_metric(e.get('kv_hit_rate'))}")
        if not sample_count_ok(len(items)):
            lines.append(f"  {T(lang, 'drill_sample_low')}")
        return "\n".join(lines)

    # --- leaf level: single request detail ---
    match = [e for e in items if (e.get("request_id") or "?") == request]
    if not match:
        return head + "\n" + T(lang, "drill_empty")
    e = match[0]
    rows = [
        f"- {T(lang, 'drill_req_id')}: {e.get('request_id', '?')}",
        f"- {T(lang, 'drill_run_id')}: {e.get('run_id', '?')}",
        f"- {T(lang, 'drill_ok') if e.get('ok') else T(lang, 'drill_fail')}",
        f"- TTFT: {_fmt_metric(e.get('ttft_ms'), True)}",
        f"- decode_tps: {_fmt_metric(e.get('decode_tps'))}",
        f"- kv_hit_rate: {_fmt_metric(e.get('kv_hit_rate'))}",
        f"- ts: {e.get('ts', '?')}",
    ]
    return "\n".join(lines + rows)


def fmt_trend_anomaly(lang: str) -> str:
    """§2.10 — TTFT slope rising + token inflation vs baseline."""
    notes = []
    if len(_TTFT_HIST) >= 10:
        recent = [_TTFT_HIST[i]["ttft_ms"] for i in range(-10, 0)]
        if recent[-1] > recent[0] * 1.2 and recent[-1] > recent[0] + 1000:
            notes.append(T(lang, "trend_rising"))
    if _TTFT_HIST:
        # token inflation heuristic: compare latest prompt_tokens in recent
        pts = [e.get("prompt_tokens") for e in _obs_state.get("recent") or []
               if isinstance(e.get("prompt_tokens"), (int, float))]
        if len(pts) >= 5:
            base = sum(pts[:-5]) / max(1, len(pts) - 5)
            if base and pts[-1] > base * 1.3:
                notes.append(T(lang, "trend_inflating"))
    if not notes:
        return T(lang, "trend_none")
    return f"{T(lang,'trend_anomaly_title')}\n" + "\n".join(f"- {n}" for n in notes)


# ---- governor (P4, §2.8) ----

def ingest_gov_event(kind: str, data: dict) -> None:
    """Capture a governor event for the UI card (testable hook for drain_events).

    Called from ``drain_events`` for ``governor_alert`` / ``governor_action`` /
    ``governor_thinking`` / ``governor_ctx`` / ``governor_kv``. On the UI path
    the orchestrator runs with no governor, so these never fire today — but the
    hook guarantees that if any entry enables a governor, events are captured
    instead of silently dropped (defensive, §2.8 D1).
    """
    _GOV_EVENTS.append({
        "ts": time.time(),
        "kind": "alert" if kind == "governor_alert" else (
            data.get("kind") if kind == "governor_action" else kind),
        "reason": (data.get("reason")
                   or data.get("message")
                   or kind),
    })


def fmt_governor(lang: str) -> str:
    """Governor card. Honestly shows 'disabled' on the UI path as ONE concise
    line — not a long static "what it would do" essay (that read as meaningless
    noise on every render; the actionable hints already live on the metric
    cards). If governor events are ever observed (future / tight mode), shows
    mode/actions/alerts.
    """
    if not _GOV_EVENTS:
        return _span(T(lang, "gov_disabled"), "warn")
    # enabled path (defensive — events present)
    head = _span(T(lang, "gov_enabled_title"), "ok")
    actions = [e for e in _GOV_EVENTS if e.get("kind") != "alert"]
    alerts = [e for e in _GOV_EVENTS if e.get("kind") == "alert"]
    a_lines = []
    for e in actions[-8:]:
        ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
        a_lines.append(f"{ts} {e.get('kind')}: {e.get('reason','')}")
    al_lines = []
    for e in alerts[-4:]:
        ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
        al_lines.append(f"{ts} {e.get('reason','')}")
    # stability: did it oscillate (down then up) within the window?
    kinds = [e.get("kind") for e in actions]
    osc = ("set_ctx" in kinds and kinds.index("set_ctx") < len(kinds) - 1
           and "set_ctx" in kinds[kinds.index("set_ctx") + 1:])
    stable = _span(T(lang, "gov_stable_ok"), "ok") if not osc \
        else _span(T(lang, "gov_stable_bad"), "warn")
    out = [head,
            f"- {T(lang, 'gov_enabled_title')}：{T(lang, 'gov_enabled_status')}",
            f"- {T(lang, 'gov_mode')}：{T(lang, 'gov_mode_enabled')}",
            f"- {T(lang, 'gov_actions')}：",
            "\n".join(a_lines) or T(lang, "gov_none"),
            f"- {T(lang, 'gov_alerts')}：",
            "\n".join(al_lines) or T(lang, "gov_none"),
            f"- {T(lang, 'gov_stable')}：{stable}"]
    return "\n".join(out)


# ---- A/B compare (P4, §2.9) ----
# split_ab_windows / sample_count_ok / compare_windows moved to
# screwshell.ui.analysis (pure, gradio-free, unit-tested).

def fmt_ab_compare(result: Optional[dict], lang: str) -> str:
    if result is None:
        return T(lang, "ab_no_data")
    if result.get("verdict") == "sample_low":
        return T(lang, "ab_sample_low", na=result["na"], nb=result["nb"])
    if result.get("verdict") == "single_value":
        return (f"{T(lang, 'ab_time_label')}\n\n"
                f"{T(lang, 'ab_single_value')}")
    if not result.get("ok"):
        return T(lang, "ab_no_data")
    zh = lang == "zh"
    rows = [T(lang, "ab_time_label"),
            T(lang, "ab_title"),
            f"  A n={result['na']} · B n={result['nb']} · {T(lang,'ab_diff_note')}"]
    label_map = {"ttft_ms": T(lang, "ab_metric_ttft"),
                 "avg_decode_tps": T(lang, "ab_metric_tps"),
                 "kv_hit_rate": T(lang, "ab_metric_kv"),
                 "ok_rate": T(lang, "ab_metric_ok")}
    for m, lbl in label_map.items():
        ma, mb = result["means"][m]
        ma_s = f"{ma:.2f}" if isinstance(ma, float) else "n/a"
        mb_s = f"{mb:.2f}" if isinstance(mb, float) else "n/a"
        mark = " ◀" if m == result["main"] else ""
        rows.append(f"- {lbl}{mark}：A {ma_s} → B {mb_s}")
    v = result["verdict"]
    if v == "b":
        rows.append(f"\n✅ {T(lang,'ab_verdict_b')}")
    elif v == "a":
        rows.append(f"\n✅ {T(lang,'ab_verdict_a')}")
    else:
        rows.append(f"\n{T(lang,'ab_verdict_tie')}")
    if _AB_BASELINE_DESC:
        rows.append(f"\n{T(lang,'ab_baseline')}：{_AB_BASELINE_DESC}")
    return "\n".join(rows)


# ---- config versions (P4, §2.9, D3 /props snapshot) ----
# _normalize_settings / build_config_snapshot / rollback_command moved to
# screwshell.ui.analysis (pure, gradio-free, unit-tested).

def fmt_config_versions(lang: str) -> str:
    if not _CONFIG_VERSIONS:
        return T(lang, "cfg_none")
    lines = [T(lang, "cfg_title")]
    prev = None
    for snap in reversed(_CONFIG_VERSIONS):
        ts = time.strftime("%m-%d %H:%M:%S", time.localtime(snap.get("ts", 0)))
        vid = snap["vid"]
        base_mark = f" ← {T(lang,'ab_baseline')}" if vid == _CONFIG_BASELINE else ""
        lines.append(f"\n**{vid}** ({ts}){base_mark}")
        s = snap.get("settings", {})
        eff = snap.get("effective", {})
        if s:
            lines.append("  " + ", ".join(
                f"{k}={v} ({eff.get(k, 'restart')})" for k, v in s.items()))
        if prev is not None:
            diff = {k: v for k, v in s.items()
                    if prev.get("settings", {}).get(k) != v}
            if diff:
                lines.append(f"  {T(lang,'cfg_diff')}："
                             + ", ".join(f"{k}:{prev.get('settings',{}).get(k)}→{v}"
                                         for k, v in diff.items()))
            else:
                lines.append(f"  {T(lang,'cfg_no_diff')}")
        prev = snap
    lines.append(f"\n{T(lang,'cfg_rollback')}：")
    if _CONFIG_VERSIONS:
        lines.append("```\n" + rollback_command(_CONFIG_VERSIONS[-1]) + "\n```")
    return "\n".join(lines)


# ---- stream formatting (with filter + color) ----

def _stream_match(e: dict) -> bool:
    f = _STREAM_FILTER
    if f.get("entry") != "all":
        entry = "api" if e.get("entry") == "api" else "ui"
        want = "opencode" if f["entry"] == "opencode" else "ui"
        if entry != want:
            return False
    if f.get("expert") != "all":
        if (e.get("adapter") or "基础") != f["expert"]:
            return False
    if f.get("ok") == "ok" and not e.get("ok"):
        return False
    if f.get("ok") == "fail" and e.get("ok"):
        return False
    return True


def fmt_activity_stream(recent: list[dict], lang: str) -> str:
    rows = []
    for e in (_STREAM_FILTER and [x for x in (recent or []) if _stream_match(x)]) or []:
        ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
        entry = "opencode" if e.get("entry") == "api" else "UI"
        adapter = e.get("adapter") or "基础"
        ok = _span("✓", "ok") if e.get("ok") else _span("✗", "alert")
        tps = e.get("decode_tps")
        tps_s = f" {tps:.0f}t/s" if isinstance(tps, (int, float)) else ""
        msg = e.get("user_msg")
        msg_s = f" 「{msg[:38]}」" if msg else ""
        pt = e.get("prompt_tokens") or 0
        warn = _span(" ⚠️会话过长", "warn") if is_prompt_long(pt) else ""
        rows.append(f"{ts} [{entry}] 专家{adapter}{ok}{tps_s} {pt}tok{warn}{msg_s}")
    return "\n".join(rows) if rows else "（—）"


def expert_choices(recent: list[dict]) -> list[tuple]:
    """§2.10 — derive the expert dropdown choices from distinct adapters seen
    in recent events (keep "all" first)."""
    seen = []
    for e in (recent or []):
        a = e.get("adapter") or "基础"
        if a not in seen:
            seen.append(a)
    choices = [("全部", "all")] + [(a, a) for a in seen]
    return choices


def fmt_lora(expert: dict, recent: list[dict], lang: str) -> str:
    """Current expert + recent switch trail, from relay-observed events."""
    h = expert or _obs_state.get("health") or {}
    cur = h.get("current_expert")
    zh = lang == "zh"
    head = (f"当前专家: {cur or '基础(无LoRA)'}" if zh
            else f"expert: {cur or 'base'}")
    trail = []
    for e in (recent or [])[:12]:
        if e.get("switched"):
            ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
            prev = e.get("route") or "base"
            to = e.get("adapter") or "base"
            trail.append(f"{ts} {prev} → {to}")
    body = "\n".join(trail) if trail else ("（无切换记录）" if zh else "(no switches)")
    return f"{head}\n{body}"


def fmt_tools(recent: list[dict], lang: str) -> str:
    rows = []
    for e in (_STREAM_FILTER and [x for x in (recent or []) if _stream_match(x)]) or []:
        for tc in e.get("tool_calls") or []:
            ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
            name = tc.get("name") or "?"
            if name.startswith("→"):
                rows.append(f"{ts} {name} {str(tc.get('args'))[:90]}")
            else:
                rows.append(f"{ts} 调 {name}({str(tc.get('args'))[:90]})")
    if not rows:
        return T("zh" if False else lang, "no_tools")
    return "\n".join(rows[-15:])


# ---------------------------------------------------------------------------
# DataFrames for charts
# ---------------------------------------------------------------------------

# Max points per time-series chart. 180 raw points would stack every tick on the
# x-axis ("密密麻麻"); we downsample to this many, keeping the freshest samples,
# and render x as a datetime so the axis ticks stay sparse and readable.
# (2026-08-05: reverted from datetime — gradio 6.22's LinePlot frontend calls
# .replace() on x values and crashes with "e.replace is not a function" on
# datetime cells. Keep x as an HH:MM:SS string; the downsample to <=40 points
# alone is enough to keep the axis sparse/readable.)
_MAX_PLOT_POINTS = 15


def _ts_df(hist: "deque", cols: tuple, max_pts: int = _MAX_PLOT_POINTS) -> pd.DataFrame:
    """Downsample a ring buffer into a plot-ready DataFrame.

    x stays an HH:MM:SS string (gradio LinePlot frontend requires strings and
    crashes on datetime). Downsampling to <=40 points keeps the axis readable.
    Empty buffers keep a stable schema.
    """
    cols_list = ["t"] + list(cols)
    if not hist:
        return pd.DataFrame({c: [] for c in cols_list})
    pts = list(hist)
    step = max(1, len(pts) // max_pts)
    pts = pts[::step][-max_pts:]
    rows = [{
        "t": datetime.fromtimestamp(d["ts"]).strftime("%H:%M:%S"),
        **{c: d[c] for c in cols},
    } for d in pts]
    return pd.DataFrame(rows)


def _gpu_df() -> pd.DataFrame:
    # Single series (vram_pct): the multi-y LinePlot (vram+util) with an
    # all-zero util series failed to render on gradio 6.22 + pandas 3.0 (the
    # 实时 tab's first chart stayed on a spinner). util is 0 when idle anyway;
    # busy/idle is already surfaced by the "推理槽" line in the status block.
    return _ts_df(_GPU_HIST, ("vram_pct",))


def _tps_df() -> pd.DataFrame:
    return _ts_df(_TPS_HIST, ("tps",))


def _ttft_df() -> pd.DataFrame:
    return _ts_df(_TTFT_HIST, ("ttft_ms",))


def _kv_df() -> pd.DataFrame:
    return _ts_df(_KV_HIST, ("kv_hit_rate",))


def fmt_timeline(lang: str) -> str:
    """方向 B: chronological ReAct step timeline for the Stream tab. Reads the
    module-global ``_UI_STATE`` timeline (planning → steps → finalizing) and
    renders it as a live, intuitive step view."""
    zh = lang == "zh"
    tl = _UI_STATE.get("timeline") or []
    if not tl and not _UI_STATE.get("plan"):
        return T(lang, "tl_none")
    out = []
    if _UI_STATE.get("plan"):
        out.append(T(lang, "tl_task", task=_UI_STATE["plan"]))
    i, n = _UI_STATE.get("phase_i", 0), _UI_STATE.get("phase_n", 0)
    for rec in tl:
        kind = rec.get("kind")
        if kind == "planning":
            out.append("🟡 " + T(lang, "tl_planning"))
        elif kind == "finalizing":
            out.append("🟢 " + T(lang, "tl_finalizing"))
        elif kind == "step":
            desc = rec.get("desc", "")
            skill = rec.get("skill", "")
            if rec.get("status") == "running":
                label = T(lang, "tl_step_run", i=i, n=n, desc=desc, skill=skill)
                out.append("🔵 " + label)
            else:
                label = T(lang, "tl_step", i=i, n=n, desc=desc)
                out.append("✅ " + T(lang, "tl_done", desc=label))
    if zh:
        return "\n".join(out)
    return "\n".join(out)


def _slots_line(lang: str) -> str:
    sl = _obs_state.get("slots")
    if not isinstance(sl, list) or not sl:
        return ""
    busy = [s for s in sl if s.get("is_processing")]
    zh = lang == "zh"
    if busy:
        s = busy[0]
        prog = s.get("n_prompt_tokens_processed") or 0
        total = s.get("n_prompt_tokens") or 0
        return (f"推理槽: slot {s.get('id','?')} 处理中（{prog}/{total}）"
                if zh else f"slot {s.get('id','?')} processing ({prog}/{total})")
    return "推理槽: 空闲" if zh else "slot: idle"


def _status_block(lang: str) -> str:
    """Status block (phase + elapsed + slot line). Signature preserved for
    tests/test_switch_ms.py (reads module globals _UI_STATE / _obs_state).

    Phase-aware, not hardcoded: the phase text is always the primary line and
    is never overwritten by a generic "connecting/switching" message. Elapsed is
    shown only while a phase is genuinely in progress; ``quick`` means the
    answer is already done, so it reports the total time instead of a growing
    in-progress timer (fix: contradictory "快速回复 + 已 Ns + 空闲槽").
    """
    zh = lang == "zh"
    phase = phase_text(lang, _UI_STATE["phase"],
                       _UI_STATE["phase_i"], _UI_STATE["phase_n"])
    elapsed = int(time.time() - _UI_STATE["start_ts"]) if _UI_STATE["start_ts"] else 0
    sl = _slots_line(lang)
    # Idle default: user has not started any investigation yet. Show a calm
    # "ready" state instead of the misleading "调查中…" (fix: contradictory
    # idle + in-progress status). Real phases (thinking/quick/step/...) keep
    # their existing behavior unchanged below.
    if _UI_STATE["phase"] == "idle" and not _UI_STATE["start_ts"]:
        return (T(lang, "idle") + "\n" + sl) if sl else T(lang, "idle")
    th = _UI_STATE.get("thinking", "")
    # Live thought text is the most informative signal while the model thinks.
    if th:
        th_s = (f"思考中: {th[:80]}{'…' if len(th) > 80 else ''}"
                if zh else f"thinking: {th[:80]}{'…' if len(th) > 80 else ''}")
        base = (f"{th_s}\n（已 {elapsed}s · 模型生成中…）"
                if elapsed >= 2 else th_s)
        return (base + "\n" + sl) if sl else base
    # quick = the orchestrator already finished the direct answer. Do NOT show
    # a growing "in progress" timer or a "switching" line; report the total.
    if _UI_STATE["phase"] == "quick":
        base = (f"{phase}\n\n⏱ 本次回答耗时 {elapsed}s"
                if elapsed > 0 else phase)
        return (base + "\n" + sl) if sl else base
    # Remaining phases (planning / step / finalizing / thinking w/o stream):
    # primary = phase text; elapsed + expert-switch note as secondary info.
    lines = [phase]
    if elapsed >= 2:
        lines.append(f"⏱ 已 {elapsed}s · 进行中…")
    sw = (_obs_state.get("summary") or {}).get("avg_switch_ms")
    if isinstance(sw, (int, float)):
        lines.append(f"（切换约 {sw:.0f}ms）" if zh
                     else f"(switch ~{sw:.0f}ms)")
    base = "\n\n".join(lines)
    return (base + "\n" + sl) if sl else base


# ---------------------------------------------------------------------------
# Single source of truth for dashboard output ordering. dashboard_values(),
# respond() yield, auto_refresh(), and apply_lang() all derive from this list,
# so the four sites can never drift (V2/P1 foot-gun).
# ---------------------------------------------------------------------------

DASH_NAMES = [
    # Overview
    "health", "metrics", "percentiles", "causal",
    # Live
    "status", "gpu", "tps", "ttft", "kv", "trend_anomaly", "governor",
    # Stream
    "switch_log", "tools", "activity", "evidence", "audit", "plan",
    # Tuning
    "ab_compare", "config_versions", "rollback",
    "tune_progress", "tune_status",
]


def dashboard_values(lang: str) -> tuple:
    global _CUR_LANG
    lang = norm_lang(lang)
    _CUR_LANG = lang
    # Health banner + metric cards judge the CURRENT operational session
    # (p95, benchmark-excluded) when available; fall back to the global
    # summary for drill-down / first-boot (no session yet).
    s = _obs_state.get("session_summary") or _obs_state.get("summary")
    recent = _obs_state.get("recent") or []
    expert = _obs_state.get("expert") or _obs_state.get("health") or {}
    slots = _obs_state.get("slots")
    audit = "\n".join(
        f"{e['time']} {e['event']} {json.dumps({k: v for k, v in e.items() if k not in ('ts', 'time', 'event')}, default=str)[:120]}"
        for e in ctx_audit().tail(12)) if _CTX is not None else ""
    plan = _UI_STATE["plan"] or T(lang, "ext_no_data")
    ev = (ctx_evidence().context_block(limit=8)
          if _CTX is not None else "") or T(lang, "ext_no_data")
    audit = (audit or T(lang, "ext_no_data"))
    return (
        fmt_health_banner(s, lang),                       # health
        fmt_metric_cards(s, lang),                        # metrics
        fmt_session_request_drilldown(recent, _DRILL_SESSION,
                                       _DRILL_REQUEST, lang),  # percentiles slot -> drill
        causal_hint(s, slots, recent, lang),              # causal
        _status_block(lang),                              # status
        _gpu_df(),                                        # gpu
        _tps_df(),                                        # tps
        _ttft_df(),                                       # ttft
        _kv_df(),                                         # kv
        fmt_trend_anomaly(lang),                          # trend_anomaly
        fmt_governor(lang),                               # governor
        fmt_lora(expert, recent, lang),                   # switch_log
        fmt_tools(recent, lang),                          # tools
        fmt_activity_stream(recent, lang),                # activity
        ev,                                               # evidence
        audit,                                            # audit
        fmt_timeline(lang),                              # plan (方向 B step timeline)
        fmt_ab_compare(_AB_RESULT, lang),                 # ab_compare
        fmt_config_versions(lang),                        # config_versions
        (rollback_command(_CONFIG_VERSIONS[-1])
         if _CONFIG_VERSIONS else T(lang, "cfg_none")),   # rollback
        T(lang, "tune_status_idle"),                       # tune_progress
        "",                                                # tune_status
    )


# ctx holders (set in make_ui; dashboard_values reads them lazily so the module
# stays importable in tests without a full AppContext).
_CTX = None


def ctx_audit():
    return _CTX.gate.audit if _CTX is not None else None


def ctx_evidence():
    return _CTX.evidence if _CTX is not None else None


def make_ui(ctx):
    global _CTX
    _CTX = ctx
    events: "queue.Queue[tuple[str, dict]]" = queue.Queue()
    ctx.orchestrator.on_event = lambda kind, data: events.put((kind, data))
    _start_observ_poller()

    streamed = {"text": ""}

    def drain_events():
        while True:
            try:
                kind, data = events.get_nowait()
            except queue.Empty:
                break
            if kind == "plan":
                _UI_STATE["plan"] = data["task"]
            elif kind == "lora_switch":
                _UI_STATE["lora"].append(
                    f"{(data.get('from') or '基础')} → {(data.get('to') or '基础')} "
                    f"（{data['ms']:.1f} 毫秒，技能={data['skill']}）")
            elif kind == "tool":
                _UI_STATE["tools"].append(
                    f"[{'成功' if data['ok'] else '失败'}] {data['tool']}: "
                    f"{data['digest'][:160]}")
            elif kind == "generation":
                _UI_STATE["gens"].append(
                    f"{data['adapter'] or '基础'}: {data['tokens_per_s']} tok/s "
                    f"（{data['new_tokens']} tokens）")
            elif kind == "answer_chunk":
                streamed["text"] += data.get("text", "")
            elif kind == "thinking":
                _UI_STATE["thinking"] = data.get("text", "")
            elif kind == "phase":
                t = data.get("text", "thinking")
                if t.startswith("step_"):
                    rest = t[len("step_"):]
                    try:
                        a, _, b = rest.partition("_")
                        _UI_STATE["phase"] = "step"
                        _UI_STATE["phase_i"] = int(a)
                        _UI_STATE["phase_n"] = int(b)
                    except ValueError:
                        _UI_STATE["phase"] = "thinking"
                else:
                    _UI_STATE["phase"] = t
                # 方向 B step timeline: record planning / finalizing markers
                # and close out any still-running step.
                if t == "planning":
                    _timeline_close_running()
                    _UI_STATE["timeline"].append(
                        {"kind": "planning", "ts": time.time()})
                elif t == "finalizing":
                    _timeline_close_running()
                    _UI_STATE["timeline"].append(
                        {"kind": "finalizing", "ts": time.time()})
                _timeline_trim()
            elif kind == "step_start":
                _timeline_close_running()
                _UI_STATE["timeline"].append({
                    "kind": "step",
                    "desc": data.get("desc", ""),
                    "skill": data.get("skill", ""),
                    "status": "running",
                    "ts": time.time(),
                })
                _timeline_trim()
            elif kind == "step_done":
                _timeline_close_running()
                _timeline_trim()
            elif kind in ("governor_alert", "governor_action",
                          "governor_thinking", "governor_ctx", "governor_kv"):
                # P4 (§2.8): defensive — the UI path runs with no governor, so
                # these never fire today; but if any entry enables a governor,
                # the events are captured here instead of silently dropped.
                ingest_gov_event(kind, data)

    def run_ab(window_min):
        # A/B is now time-only: split recent into A(before)/B(after) by the
        # minute window. No dimension dropdown (方案 B / Q2 方案 (a)).
        global _AB_RESULT
        recent = _obs_state.get("recent") or []
        _AB_RESULT = run_ab_split(recent, "time", float(window_min or 10))
        return gr.update(value=fmt_ab_compare(_AB_RESULT, _CUR_LANG))

    def set_baseline(window_min):
        global _AB_RESULT, _AB_BASELINE_DESC
        recent = _obs_state.get("recent") or []
        result = run_ab_split(recent, "time", float(window_min or 10))
        _AB_RESULT = result
        _AB_BASELINE_DESC = (f"A n={result['na']} / B n={result['nb']}")
        return gr.update(value=T(_CUR_LANG, "ab_baseline_set",
                                  desc=_AB_BASELINE_DESC))

    # ----------------------- auto-tune (tune-loop plan, Todo 7) -----------------------
    def start_tune(preset):
        """Trigger the one-click tune cycle via the relay (no local restart)."""
        resp = _tune_post("/v1/tune/start", {"preset": preset})
        if resp is None:
            return (gr.update(value=T(_CUR_LANG, "tune_status_abort")),
                    gr.update(value="relay unreachable"))
        if resp.get("status_code") == 401:
            return (gr.update(value=T(_CUR_LANG, "tune_status_abort")),
                    gr.update(value="unauthorized (X-Relay-Token)"))
        if resp.get("status_code") == 409:
            return (gr.update(value=T(_CUR_LANG, "tune_status_running")),
                    gr.update(value=resp.get("error", "already running")))
        return (gr.update(value=T(_CUR_LANG, "tune_status_running")),
                gr.update(value=str(resp)))

    def stop_tune():
        resp = _tune_post("/v1/tune/stop", {})
        if resp is None:
            return gr.update(value="relay unreachable")
        return gr.update(value=str(resp))

    def _poll_tune_status() -> tuple:
        """Called by the dashboard timer to refresh the tune panel."""
        resp = _obs_get("/v1/tune/status")
        if resp is None:
            return (gr.update(value=T(_CUR_LANG, "tune_status_idle")),
                    gr.update(value=""))
        status = resp.get("status", "idle")
        label = {
            "idle": T(_CUR_LANG, "tune_status_idle"),
            "running": T(_CUR_LANG, "tune_status_running"),
            "done": T(_CUR_LANG, "tune_status_done"),
            "abort": T(_CUR_LANG, "tune_status_abort"),
            "rollback": T(_CUR_LANG, "tune_rolling_back"),
        }.get(status, status)
        if resp.get("server_may_be_down"):
            label += " — SERVER MAY BE DOWN"
        hist = resp.get("history") or []
        progress = T(_CUR_LANG, "tune_progress") + f": {status}, {len(hist)} steps"
        return (gr.update(value=label), gr.update(value=progress))
    def apply_filter(entry, expert, ok):
        _STREAM_FILTER["entry"] = entry or "all"
        _STREAM_FILTER["expert"] = expert or "all"
        _STREAM_FILTER["ok"] = ok or "all"
        recent = _obs_state.get("recent") or []
        return (gr.update(value=fmt_activity_stream(recent, _CUR_LANG)),
                gr.update(value=fmt_tools(recent, _CUR_LANG)))

    def _drill(drill_session, drill_request):
        global _DRILL_SESSION, _DRILL_REQUEST
        _DRILL_SESSION = drill_session or None
        # selecting a session clears any stale request; selecting a request
        # keeps the session.
        _DRILL_REQUEST = drill_request or None
        recent = _obs_state.get("recent") or []
        return gr.update(
            value=fmt_session_request_drilldown(recent, _DRILL_SESSION,
                                                _DRILL_REQUEST, _CUR_LANG))

    def _build_session_choices():
        # Live list of all operation sessions (parent level), kept current so
        # the dropdown reflects events flowing in. "all" stays first.
        recent = _obs_state.get("recent") or []
        hierarchy = session_request_hierarchy(recent)
        choices = [(T(_CUR_LANG, "drill_all_sessions"), "all")]
        for sid in sorted(hierarchy.keys()):
            label = (T(_CUR_LANG, "drill_no_session")
                     if sid == "(no-session)" else sid)
            choices.append((f"{label} ({T(_CUR_LANG, 'drill_n_requests', n=len(hierarchy[sid])).replace('n 次请求=', '')})", sid))
        return choices

    def apply_session(session):
        # changing the session resets the request drill and repopulates the
        # request dropdown with that session's children. It also refreshes the
        # session dropdown's own choices from the live data (fix: the session
        # list was never populated, so the user could not pick a specific one).
        global _DRILL_SESSION, _DRILL_REQUEST
        _DRILL_SESSION = session or None
        _DRILL_REQUEST = None
        recent = _obs_state.get("recent") or []
        hierarchy = session_request_hierarchy(recent)
        items = hierarchy.get(_DRILL_SESSION, []) if _DRILL_SESSION else []
        req_choices = [("全部请求", "all")] + [
            (e.get("request_id") or "?", e.get("request_id") or "?")
            for e in sorted(items, key=lambda e: e.get("ts") or 0)
            if e.get("request_id")]
        sess_update = gr.update(choices=_build_session_choices(),
                                value=(_DRILL_SESSION or "all"))
        req_update = gr.update(choices=req_choices, value="all", interactive=bool(items))
        return (sess_update, req_update,
                _drill(_DRILL_SESSION, None))

    def apply_request(request):
        # request == "all" means "session level" (no single request selected).
        req = None if (not request or request == "all") else request
        return _drill(_DRILL_SESSION, req)

    def respond(message, chat_history, lang, think, deep):
        lang = norm_lang(lang)
        chat_history = chat_history + [{"role": "user", "content": message}]
        ctx.orchestrator._force_deep = bool(deep)
        ctx.orchestrator._thinking_on = bool(think)
        _UI_STATE["phase"] = "thinking"
        _UI_STATE["phase_i"] = 0
        _UI_STATE["phase_n"] = 0
        _UI_STATE["start_ts"] = time.time()
        streamed["text"] = ""

        result_box = {}

        def work():
            result_box["r"] = ctx.orchestrator.run(message)

        th = threading.Thread(target=work, daemon=True)
        th.start()
        while th.is_alive():
            th.join(timeout=1.0)
            drain_events()
            if streamed["text"]:
                content = streamed["text"]
            else:
                phase = phase_text(lang, _UI_STATE["phase"],
                                   _UI_STATE["phase_i"], _UI_STATE["phase_n"])
                elapsed = int(time.time() - _UI_STATE["start_ts"])
                content = (f"{phase}\n（已 {elapsed}s · 模型生成中…）"
                           if elapsed >= 2 else phase)
            yield (chat_history + [{"role": "assistant", "content": content}],
                   *dashboard_values(lang))
        drain_events()
        r = result_box.get("r")
        answer = r.answer if r else T(lang, "err")
        yield (chat_history + [{"role": "assistant", "content": answer}],
               *dashboard_values(lang))

    def respond_wrapper(message, chat_history, lang, think, deep):
        for tup in respond(message, chat_history, lang, think, deep):
            yield tup

    def apply_lang(lang):
        lang = norm_lang(lang)
        d = dashboard_values(lang)
        return (
            gr.update(value=T(lang, "title")),                     # title_md
            gr.update(value=lang),                                 # lang_dd
            gr.update(label=T(lang, "msg_label"),
                      placeholder=T(lang, "msg_ph")),              # msg
            gr.update(value=T(lang, "send")),                      # send
            *d,
        )

    with gr.Blocks(title="ScrewShell — 私有本地调查员 · 观测台") as demo:
        title_md = gr.Markdown(T("zh", "title"))
        with gr.Row():
            lang_dd = gr.Dropdown(choices=LANG_CHOICES, value="zh", type="value",
                                  label=T("zh", "lang"), scale=1, min_width=120)
            think_cb = gr.Checkbox(value=False, label=T("zh", "think"), scale=2)
            deep_cb = gr.Checkbox(value=False, label=T("zh", "deep"), scale=2)

        with gr.Row():
            # ---- Left: chat console ----
            with gr.Column(scale=3):
                chat = gr.Chatbot(height=560, label=T("zh", "chat_label"))
                msg = gr.Textbox(label=T("zh", "msg_label"),
                                 placeholder=T("zh", "msg_ph"))
                send = gr.Button(T("zh", "send"), variant="primary")

            # ---- Right: observatory dashboard (4 views) ----
            with gr.Column(scale=2):
                with gr.Tabs():
                    # ===== Overview =====
                    with gr.Tab(T("zh", "tab_overview")):
                        health_md = gr.Markdown(value=fmt_health_banner(
                            _obs_state.get("summary"), "zh"),
                            label=T("zh", "obs_summary_label"))
                        metrics_md = gr.Markdown(value=fmt_metric_cards(
                            _obs_state.get("summary"), "zh"),
                            label=T("zh", "obs_summary_label"))
                        # 方向 B drill-down (cascading session -> request).
                        # Renders into the percentiles slot (reused to keep
                        # DASH_NAMES at 20). Not in comps/dash_outs.
                        with gr.Row():
                            session_dd = gr.Dropdown(
                                choices=_build_session_choices(),
                                value="all", type="value",
                                label=T("zh", "drill_session"), scale=2)
                            request_dd = gr.Dropdown(
                                choices=[(T("zh", "drill_all_sessions"), "all")],
                                value="all", type="value",
                                label=T("zh", "drill_request"), scale=2,
                                interactive=False)
                        percentiles_md = gr.Markdown(
                            value=fmt_session_request_drilldown(
                                _obs_state.get("recent"), None, None, "zh"))
                        causal_md = gr.Markdown(value="")
                    # ===== Live =====
                    with gr.Tab(T("zh", "tab_live")):
                        status_md = gr.Markdown(value=_status_block("zh"),
                                                label=T("zh", "status_label"))
                        with gr.Group():
                            gpu_plot = gr.LinePlot(
                                value=_gpu_df(), x="t",
                                y="vram_pct",
                                title=T("zh", "gpu_chart_title"), height=160)
                        with gr.Group():
                            tps_plot = gr.LinePlot(
                                value=_tps_df(), x="t", y="tps",
                                title=T("zh", "tps_chart_title"), height=140)
                        with gr.Group():
                            ttft_plot = gr.LinePlot(
                                value=_ttft_df(), x="t", y="ttft_ms",
                                title=T("zh", "ttft_chart_title"), height=140)
                        with gr.Group():
                            kv_plot = gr.LinePlot(
                                value=_kv_df(), x="t", y="kv_hit_rate",
                                title=T("zh", "kv_chart_title"), height=140)
                        trend_anomaly_md = gr.Markdown(value="")
                        governor_md = gr.Markdown(value=fmt_governor("zh"),
                                                  label=T("zh", "gov_enabled_title"))
                    # ===== Stream =====
                    with gr.Tab(T("zh", "tab_stream")):
                        with gr.Row():
                            f_entry = gr.Dropdown(
                                choices=[("全部", "all"), ("opencode", "opencode"),
                                         ("UI", "ui")], value="all", type="value",
                                label=T("zh", "filter_entry"), scale=1)
                            f_expert = gr.Dropdown(
                                choices=expert_choices(_obs_state.get("recent")),
                                value="all", type="value",
                                label=T("zh", "filter_expert"), scale=1)
                            f_ok = gr.Dropdown(
                                choices=[("全部", "all"), ("仅成功", "ok"),
                                         ("仅失败", "fail")], value="all", type="value",
                                label=T("zh", "filter_ok"), scale=1)
                        switch_md = gr.Textbox(value=fmt_lora(
                            _obs_state.get("expert"), _obs_state.get("recent"), "zh"),
                            label=T("zh", "lora_label"), lines=6)
                        tools_md = gr.Textbox(value=fmt_tools(
                            _obs_state.get("recent"), "zh"),
                            label=T("zh", "tools_label"), lines=8)
                        obs_recent_md = gr.Textbox(value=fmt_activity_stream(
                            _obs_state.get("recent"), "zh"),
                            label=T("zh", "obs_recent_label"), lines=12)
                        ev_md = gr.Textbox(value=T("zh", "ext_no_data"),
                                           label=T("zh", "ev_label"), lines=8)
                        audit_md = gr.Textbox(value=T("zh", "ext_no_data"),
                                              label=T("zh", "audit_label"), lines=6)
                        plan_md = gr.Textbox(value=T("zh", "ext_no_data"),
                                             label=T("zh", "plan_label"), lines=6)
                    # ===== Tuning =====
                    with gr.Tab(T("zh", "tab_tuning")):
                        # A/B is time-only: split A(before)/B(after) by minute
                        # window (Q2 方案 (a)). No dimension dropdown.
                        with gr.Row():
                            ab_win = gr.Number(value=10, label=T("zh", "ab_window_min"),
                                              scale=1)
                        with gr.Row():
                            ab_run_btn = gr.Button(T("zh", "ab_run"))
                            ab_base_btn = gr.Button(T("zh", "ab_set_baseline"))
                        ab_compare_md = gr.Markdown(value=T("zh", "ab_no_data"))
                        config_versions_md = gr.Markdown(value=T("zh", "cfg_none"))
                        rollback_md = gr.Textbox(value=T("zh", "cfg_none"),
                                                 label=T("zh", "cfg_rollback"),
                                                 lines=4)

                    # ===== Auto-Tune (one-click closed-loop tuning) =====
                    with gr.Tab(T("zh", "tab_autotune")):
                        tune_preset = gr.Radio(
                            choices=[
                                (T("zh", "tune_preset_speed"), "speed"),
                                (T("zh", "tune_preset_vram"), "vram"),
                                (T("zh", "tune_preset_ctx"), "ctx"),
                                (T("zh", "tune_preset_balance"), "balance"),
                            ],
                            value="balance", type="value",
                            label=T("zh", "tune_preset"))
                        with gr.Row():
                            tune_btn = gr.Button(T("zh", "tune_start"),
                                                 variant="primary")
                            tune_stop_btn = gr.Button(T("zh", "tune_stop"))
                        tune_progress_md = gr.Markdown(
                            value=T("zh", "tune_status_idle"))
                        tune_status_md = gr.Markdown(value="")

        # Compose the dashboard output list from the canonical DASH_NAMES order.
        comps = {
            "health": health_md, "metrics": metrics_md,
            "percentiles": percentiles_md, "causal": causal_md,
            "status": status_md, "gpu": gpu_plot, "tps": tps_plot,
            "ttft": ttft_plot, "kv": kv_plot,
            "trend_anomaly": trend_anomaly_md, "governor": governor_md,
            "switch_log": switch_md, "tools": tools_md,
            "activity": obs_recent_md, "evidence": ev_md,
            "audit": audit_md, "plan": plan_md,
            "ab_compare": ab_compare_md,
            "config_versions": config_versions_md,
            "rollback": rollback_md,
            "tune_progress": tune_progress_md,
            "tune_status": tune_status_md,
        }
        dash_outs = [comps[n] for n in DASH_NAMES]
        chat_outs = [chat] + dash_outs
        lang_outs = [title_md, lang_dd, msg, send] + dash_outs

        def auto_refresh(lang):
            lang = norm_lang(lang)
            _poll_observ_once()
            return list(dashboard_values(lang))

        def refresh_session_choices():
            # keep the session dropdown's list live as events flow in.
            return gr.update(choices=_build_session_choices())

        timer = gr.Timer(2.0)
        timer.tick(auto_refresh, lang_dd, dash_outs)
        timer.tick(refresh_session_choices, None, session_dd)
        timer.tick(_poll_tune_status, None, [tune_progress_md, tune_status_md])

        # A/B wiring (time-only)
        ab_run_btn.click(run_ab, ab_win, ab_compare_md)
        ab_base_btn.click(set_baseline, ab_win, ab_compare_md)
        # auto-tune wiring (tune-loop plan, Todo 7)
        tune_btn.click(start_tune, tune_preset, [tune_progress_md, tune_status_md])
        tune_stop_btn.click(stop_tune, None, tune_progress_md)
        # stream filter wiring
        for fctrl in (f_entry, f_expert, f_ok):
            fctrl.change(apply_filter, [f_entry, f_expert, f_ok],
                         [obs_recent_md, tools_md])
        # 方向 B drill-down wiring (cascading session -> request). Not in
        # comps/dash_outs; the percentiles slot is rendered directly.
        session_dd.change(apply_session, session_dd,
                          [session_dd, request_dd, percentiles_md])
        request_dd.change(apply_request, request_dd, percentiles_md)

        send.click(respond_wrapper, [msg, chat, lang_dd, think_cb, deep_cb],
                   chat_outs)
        msg.submit(respond_wrapper, [msg, chat, lang_dd, think_cb, deep_cb],
                   chat_outs)
        lang_dd.change(apply_lang, lang_dd, lang_outs)
    return demo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--base", default="/models/unsloth/Qwen3.5-9B")
    ap.add_argument("--lora-dir", default="/persistent/loras")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--no-rag", action="store_true", help="skip RAG index build")
    ap.add_argument("--share", action="store_true", help="expose via Gradio public share link")
    args = ap.parse_args()

    ctx = build_app(workspace=args.workspace, base=args.base,
                    lora_dir=args.lora_dir, build_rag=not args.no_rag)
    demo = make_ui(ctx)
    demo.launch(server_name="0.0.0.0", server_port=args.port, share=args.share)


if __name__ == "__main__":
    main()
