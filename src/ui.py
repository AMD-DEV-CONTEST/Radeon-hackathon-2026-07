"""
UI — Gradio Web Interface.
Enterprise audit-grade inventory risk command center.
Supports EN/ZH bilingual UI via language toggle.
Facts computed by deterministic pandas workflow; LLM only used for report expression.
"""

import gradio as gr
from pathlib import Path
import pandas as pd
import json
import os
import time
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

import plotly.graph_objects as go
import plotly.express as px

from src.llm_health import check_llm_health
from src.i18n import t, get_lang_keywords

# ── 企业级 CSS ──
APP_CSS = """
:root {
  --ink: #0f172a;
  --panel: #1e293b;
  --panel-soft: #334155;
  --line: #cbd5e1;
  --muted: #94a3b8;
  --paper: #f8fafc;
  --accent: #2563eb;
  --accent-hover: #1d4ed8;
  --risk: #b45309;
  --danger: #991b1b;
  --ok: #166534;
  --ok-light: #dcfce7;
  --risk-light: #fef3c7;
  --danger-light: #fee2e2;
  --radius: 16px;
}

.gradio-container {
  background: linear-gradient(180deg, #eef2f7 0%, #f8fafc 45%, #ffffff 100%) !important;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif !important;
}

.tabs { border: none !important; }
.tab-nav { background: transparent !important; border-bottom: 1px solid var(--line) !important; }
button.tab-nav {
  font-size: 15px !important; font-weight: 500 !important; padding: 10px 20px !important;
  color: var(--muted) !important; border: none !important; background: transparent !important;
  transition: color 0.15s, box-shadow 0.15s !important;
}
button.tab-nav.selected { color: var(--accent) !important; box-shadow: inset 0 -2px 0 var(--accent) !important; }

.audit-hero {
  background: linear-gradient(135deg, #ffffff 0%, #f1f5f9 100%);
  color: var(--ink); border-radius: var(--radius);
  padding: 22px 28px; margin-bottom: 18px;
  border: 1px solid #cbd5e1;
  box-shadow: 0 8px 22px rgba(15,23,42,0.06);
}
.audit-hero h2 { margin: 0 0 6px 0; font-size: 22px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink) !important; }
.audit-hero .hero-subtitle { font-size: 13px; color: #475569 !important; }
.audit-hero .hero-meta {
  display: flex; flex-wrap: wrap; gap: 20px; margin-top: 14px; font-size: 13px; color: #475569 !important;
}
.audit-hero .hero-meta span { display: inline-flex; align-items: center; gap: 6px; color: #475569 !important; }
.hero-tag {
  display: inline-block; background: #e0f2fe; color: #075985 !important;
  border: 1px solid #bae6fd; font-size: 11px; font-weight: 700;
  padding: 3px 10px; border-radius: 999px; letter-spacing: 0.03em;
}

.kpi-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 18px 0;
}
.kpi-card {
  background: #ffffff; border: 1px solid var(--line); border-radius: var(--radius);
  padding: 16px 18px; box-shadow: 0 4px 12px rgba(15,23,42,0.05); color: var(--ink) !important;
}
.kpi-card .kpi-label { color: var(--muted); font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
.kpi-card .kpi-value { color: var(--ink); font-size: 26px; font-weight: 760; margin-top: 4px; letter-spacing: -0.02em; }
.kpi-card .kpi-sub { color: var(--muted); font-size: 12px; margin-top: 2px; }

.card-section {
  background: #ffffff; border: 1px solid var(--line); border-radius: var(--radius);
  padding: 18px 22px; margin: 14px 0; box-shadow: 0 4px 12px rgba(15,23,42,0.04); color: var(--ink) !important;
}
.card-section h3 { margin: 0 0 10px 0; font-size: 15px; font-weight: 700; color: var(--ink); }

.stat-row { display: flex; gap: 28px; flex-wrap: wrap; }
.stat-item { min-width: 120px; }
.stat-item .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.stat-item .value { font-size: 18px; font-weight: 700; color: var(--ink); }

.risk-panel {
  border-left: 4px solid var(--risk); background: var(--risk-light);
  border-radius: 0 var(--radius) var(--radius) 0; padding: 14px 18px; margin: 14px 0;
  color: #78350f !important;
}
.risk-panel .risk-title { font-size: 13px; font-weight: 700; color: var(--risk); }

.danger-panel {
  border-left: 4px solid var(--danger); background: var(--danger-light);
  border-radius: 0 var(--radius) var(--radius) 0; padding: 14px 18px; margin: 14px 0;
  color: #7f1d1d !important;
}
.danger-panel .risk-title { font-size: 13px; font-weight: 700; color: var(--danger); }

.ok-panel {
  border-left: 4px solid var(--ok); background: var(--ok-light);
  border-radius: 0 var(--radius) var(--radius) 0; padding: 14px 18px; margin: 14px 0;
  color: #14532d !important;
}

.status-pill {
  display: inline-block; border-radius: 999px; padding: 2px 10px;
  font-size: 11px; font-weight: 700; letter-spacing: 0.02em;
}
.pill-ok { background: var(--ok-light); color: var(--ok) !important; }
.pill-risk { background: var(--risk-light); color: var(--risk) !important; }
.pill-danger { background: var(--danger-light); color: var(--danger) !important; }

.timeline-item {
  display: grid; grid-template-columns: 160px 1fr 80px; gap: 12px;
  align-items: center; padding: 10px 14px;
  border-bottom: 1px solid #f1f5f9; font-size: 13px;
}
.timeline-item:last-child { border-bottom: none; }
.timeline-item .step-name { font-weight: 600; color: var(--ink); }
.timeline-item .step-summary { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.timeline-item .step-duration { text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }

.cap-card {
  background: #ffffff; border: 1px solid var(--line); border-radius: var(--radius);
  padding: 16px 18px; flex: 1; min-width: 200px; color: var(--ink) !important;
}
.cap-card h4 { margin: 0 0 6px 0; font-size: 14px; font-weight: 700; color: var(--ink); }
.cap-card p { margin: 0; font-size: 13px; color: var(--muted); line-height: 1.5; }

.action-card {
  background: #ffffff; border: 1px solid var(--line); border-radius: var(--radius);
  padding: 14px 16px; margin: 8px 0; display: flex; align-items: flex-start; gap: 12px; color: var(--ink) !important;
}
.action-card .action-icon {
  width: 36px; height: 36px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; flex-shrink: 0;
}
.action-card .action-body h5 { margin: 0 0 2px 0; font-size: 14px; font-weight: 700; color: var(--ink); }
.action-card .action-body p { margin: 0; font-size: 12px; color: var(--muted); }

.audit-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 12px 0;
}
.audit-grid .stat-item {
  background: #ffffff; border: 1px solid var(--line);
  border-radius: 12px; padding: 14px; color: var(--ink) !important;
}
.audit-grid .stat-item .label {
  font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em;
}
.audit-grid .stat-item .value {
  font-size: 16px; font-weight: 700; color: var(--ink); margin-top: 2px;
}

.boundary-badge {
  display: inline-block; background: var(--ink); color: #f8fafc;
  font-size: 10px; font-weight: 700; padding: 2px 8px;
  border-radius: 4px; letter-spacing: 0.03em;
}
"""


class ChatEngine:
    """基于分析结果的对话引擎，支持多轮交互 + 历史持久化。"""

    def __init__(self, history_file: str = "data/chat_history.json"):
        self.analysis_result = None
        self.variance_df = None
        self.initialized = False
        self.history_file = Path(history_file)
        self.chat_history = self._load_history()
        self.lang = "en"

    def _load_history(self) -> list:
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_history(self):
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self.chat_history, f, ensure_ascii=False, indent=2)

    def get_history(self) -> list:
        return [{"role": h["role"], "content": h["content"]} for h in self.chat_history]

    def add_to_history(self, role: str, content: str):
        self.chat_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        self._save_history()

    def clear_history(self):
        self.chat_history = []
        self._save_history()

    def export_to_markdown(self) -> str:
        if not self.chat_history:
            return t("chat_export_empty", self.lang)
        lines = [
            t("chat_export_title", self.lang),
            f"\n> {t('chat_export_time', self.lang)}：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
            "---\n",
        ]
        for entry in self.chat_history:
            role = t("chat_export_user", self.lang) if entry["role"] == "user" else t("chat_export_agent", self.lang)
            timestamp = entry.get("timestamp", "")
            time_str = ""
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    time_str = f" *({dt.strftime('%H:%M')})*"
                except Exception:
                    pass
            lines.append(f"### {role}{time_str}\n")
            lines.append(f"{entry['content']}\n")
            lines.append("---\n")
        return "\n".join(lines)

    def save_markdown(self) -> str:
        md_content = self.export_to_markdown()
        export_dir = Path("data/output")
        export_dir.mkdir(parents=True, exist_ok=True)
        lang_prefix = "EN" if self.lang == "en" else "ZH"
        filename = f"ChatLog_{lang_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        filepath = export_dir / filename
        filepath.write_text(md_content, encoding="utf-8")
        return str(filepath)

    def load_analysis(self, result: dict, variance_df=None):
        self.analysis_result = result
        self.variance_df = variance_df
        self.initialized = True

    def answer(self, question: str) -> str:
        if not self.initialized:
            return t("chat_not_ready", self.lang)
        q = question.lower()
        if any(kw in q for kw in get_lang_keywords("kw_overview", self.lang)):
            return self._answer_overview()
        if any(kw in q for kw in get_lang_keywords("kw_rate", self.lang)):
            return self._answer_variance_rate()
        if any(kw in q for kw in get_lang_keywords("kw_loss", self.lang)):
            return self._answer_loss()
        if any(kw in q for kw in get_lang_keywords("kw_gain", self.lang)):
            return self._answer_gain()
        if any(kw in q for kw in get_lang_keywords("kw_anomaly", self.lang)):
            return self._answer_anomaly_category()
        if any(kw in q for kw in get_lang_keywords("kw_log", self.lang)):
            return self._answer_log_correlation()
        if any(kw in q for kw in get_lang_keywords("kw_location", self.lang)):
            return self._answer_location()
        if any(kw in q for kw in get_lang_keywords("kw_noise", self.lang)):
            return self._answer_noise()
        if any(kw in q for kw in get_lang_keywords("kw_quality", self.lang)):
            return self._answer_quality()
        if any(kw in q for kw in get_lang_keywords("kw_amount", self.lang)):
            return self._answer_amount()
        if any(kw in q for kw in get_lang_keywords("kw_recommend", self.lang)):
            return self._answer_recommendation()
        if any(kw in q for kw in get_lang_keywords("kw_top", self.lang)):
            return self._answer_top_sku()
        if any(kw in q for kw in get_lang_keywords("kw_sku", self.lang)):
            return self._answer_sku_query(question)
        if any(kw in q for kw in get_lang_keywords("kw_help", self.lang)):
            return self._answer_help()
        return self._answer_default(question)

    def _get_step(self, step_name):
        return self.analysis_result.get(step_name, {})

    def _answer_overview(self) -> str:
        L = self.lang
        step5 = self._get_step("Step 5: 加载盘点结果")
        step6 = self._get_step("Step 6: 计算差异金额")
        step7 = self._get_step("Step 7: 日志关联分析")
        lines = [
            t("chat_overview_title", L),
            f"- {t('chat_overview_sku_total', L)} **{step5.get('total_sku', 0)}**",
            f"- {t('chat_overview_sys_stock', L)} **{step5.get('system_total', 0):,}**",
            f"- {t('chat_overview_recount', L)} **{step5.get('recount_total', 0):,}**",
            f"- {t('chat_overview_net_var', L)} **{step5.get('net_variance', 0):,}**",
            f"- {t('chat_overview_var_rate', L)} **{step5.get('variance_rate', 0)}%**",
            f"- {t('chat_overview_loss_sku', L)} **{step5.get('loss_count', 0)}**",
            f"- {t('chat_overview_gain_sku', L)} **{step5.get('gain_count', 0)}**",
            f"- {t('chat_overview_correction', L)} **{step5.get('correction_count', 0)}**",
            "",
            f"{t('chat_overview_net_amt', L)} **{step6.get('net_variance_amount', 0):,.2f}**",
        ]
        if isinstance(step7, dict) and "无日志关联" in step7:
            no_log = step7["无日志关联"]
            lines.append(f"{t('chat_overview_no_log', L)} **{no_log.get('count', 0)}** {t('kpi_currency_unit', L)} {no_log.get('amount', 0):,.2f} — {t('chat_overview_no_log_note', L)}")
        lines.append("")
        lines.append("---")
        lines.append(t("chat_overview_source", L))
        return "\n".join(lines)

    def _answer_variance_rate(self) -> str:
        L = self.lang
        step5 = self._get_step("Step 5: 加载盘点结果")
        rate = step5.get("variance_rate", 0)
        level = t("chat_var_rate_normal", L) if rate < 3 else (t("chat_var_rate_watch", L) if rate < 8 else t("chat_var_rate_severe", L))
        return (
            f"{t('chat_var_rate_title', L)}\n\n"
            f"{t('kpi_variance_rate', L)}：**{rate}%**，{level}。\n\n"
            f"{t('chat_var_rate_note', L)}\n\n"
            "---\n" + t("chat_overview_source", L)
        )

    def _answer_loss(self) -> str:
        L = self.lang
        step5 = self._get_step("Step 5: 加载盘点结果")
        step6 = self._get_step("Step 6: 计算差异金额")
        return (
            f"{t('chat_loss_title', L)}\n\n"
            f"- {t('chat_loss_sku', L)} **{step5.get('loss_count', 0)}**\n"
            f"- {t('chat_loss_amt', L)} **{step6.get('total_loss_amount', 0):,.2f}**\n\n"
            f"{t('chat_loss_note', L)}\n\n"
            "---\n" + t("chat_overview_source", L)
        )

    def _answer_gain(self) -> str:
        L = self.lang
        step5 = self._get_step("Step 5: 加载盘点结果")
        step6 = self._get_step("Step 6: 计算差异金额")
        return (
            f"{t('chat_gain_title', L)}\n\n"
            f"- {t('chat_gain_sku', L)} **{step5.get('gain_count', 0)}**\n"
            f"- {t('chat_gain_amt', L)} **{step6.get('total_gain_amount', 0):,.2f}**\n\n"
            f"{t('chat_gain_note', L)}\n\n"
            "---\n" + t("chat_overview_source", L)
        )

    def _answer_anomaly_category(self) -> str:
        L = self.lang
        step9 = self._get_step("Step 9: 品类维度分析")
        categories = step9.get("categories", [])
        anomalies = step9.get("anomaly_categories", [])
        lines = [t("chat_cat_title", L) + "\n"]
        lines.append(t("chat_cat_header", L))
        lines.append("|---|---|---|---|")
        for cat in categories:
            name = cat.get("品类", "")
            rate = cat.get("差异率", 0)
            marker = " *" if rate > 5 else ""
            lines.append(f"| {name}{marker} | {cat.get('SKU数量', 0)} | {cat.get('系统库存总计', 0):,} | {rate}% |")
        if anomalies:
            lines.append(f"\n### {t('chat_cat_anomaly_title', L)}")
            for a in anomalies:
                lines.append(f"- **{a['品类']}**：{t('kpi_variance_rate', L)} {a['差异率']}%（{a['严重程度']}）")
        lines.append("")
        lines.append("---")
        lines.append(t("chat_cat_source", L))
        return "\n".join(lines)

    def _answer_log_correlation(self) -> str:
        L = self.lang
        step7 = self._get_step("Step 7: 日志关联分析")
        if not isinstance(step7, dict) or "error" in step7:
            return t("chat_log_title", L)
        lines = [t("chat_log_title", L) + "\n"]
        lines.append(t("chat_log_header", L))
        lines.append("|---|---|---|---|")
        lines.append(f"| {t('chat_log_fully', L)} | {step7.get('完全可解释', {}).get('count', 0)} | {step7.get('完全可解释', {}).get('amount', 0):,.2f} | {t('chat_log_fully_note', L)} |")
        lines.append(f"| {t('chat_log_partial', L)} | {step7.get('部分可解释', {}).get('count', 0)} | {step7.get('部分可解释', {}).get('amount', 0):,.2f} | {t('chat_log_partial_note', L)} |")
        lines.append(f"| {t('chat_log_none', L)} | {step7.get('无日志关联', {}).get('count', 0)} | {step7.get('无日志关联', {}).get('amount', 0):,.2f} | {t('chat_log_none_note', L)} |")
        lines.append("")
        lines.append("---")
        lines.append(t("chat_log_source", L))
        return "\n".join(lines)

    def _answer_location(self) -> str:
        L = self.lang
        step8 = self._get_step("Step 8: 库位状态校验")
        dist = step8.get("status_distribution", {})
        abnormal = step8.get("abnormal_count", 0)
        lines = [
            t("chat_loc_title", L) + "\n",
            f"- {t('chat_loc_active', L)} **{dist.get('启用', 0)}**",
            f"- {t('chat_loc_disabled', L)} **{dist.get('已停用', 0)}**",
            f"- {t('chat_loc_maint', L)} **{dist.get('维修中', 0)}**",
            f"- {t('chat_loc_abnormal', L)} **{abnormal}**",
            "",
            t("chat_loc_note", L),
            "",
            "---",
            t("chat_loc_source", L),
        ]
        return "\n".join(lines)

    def _answer_noise(self) -> str:
        L = self.lang
        step2 = self._get_step("Step 2: 识别噪音数据")
        noise_log = step2.get("scan_log_noise", {})
        noise_files = step2.get("noise_files", [])
        lines = [
            t("chat_noise_title", L) + "\n",
            f"### {t('chat_noise_scan_log', L)}",
            f"- {t('chat_noise_interference', L)} **{noise_log.get('noise_count', 0)}**",
            f"- {t('chat_noise_real', L)} **{noise_log.get('real_count', 0)}**",
            "",
            f"### {t('chat_noise_files', L)}",
            f"- {t('chat_noise_excluded', L)} **{len(noise_files)}** {t('chat_noise_non_applicable', L)}",
        ]
        for f in noise_files:
            lines.append(f"  - {f}")
        lines.append("")
        lines.append("---")
        lines.append(t("chat_noise_source", L))
        return "\n".join(lines)

    def _answer_quality(self) -> str:
        L = self.lang
        checks = self.analysis_result.get("quality_checks", [])
        passed = sum(1 for c in checks if c.get("passed", False))
        lines = [f"{t('chat_quality_title', L)} {passed}/{len(checks)} {t('chat_quality_passed', L)}\n"]
        for i, check in enumerate(checks, 1):
            status = "PASS" if check.get("passed") else "FAIL"
            lines.append(f"{status} **{i}. {check.get('name', '')}** ({check.get('importance', '')})")
            lines.append(f"   {check.get('detail', '')}\n")
        lines.append("---")
        lines.append(t("chat_quality_source", L))
        return "\n".join(lines)

    def _answer_amount(self) -> str:
        L = self.lang
        step6 = self._get_step("Step 6: 计算差异金额")
        return (
            f"{t('chat_amt_title', L)}\n\n"
            f"- {t('chat_amt_loss', L)} **{step6.get('total_loss_amount', 0):,.2f}**\n"
            f"- {t('chat_amt_gain', L)} **{step6.get('total_gain_amount', 0):,.2f}**\n"
            f"- {t('chat_amt_net', L)} **{step6.get('net_variance_amount', 0):,.2f}**\n"
            f"- {t('chat_amt_missing_cost', L)} **{step6.get('missing_cost_count', 0)}** {t('chat_amt_missing_note', L)}\n\n"
            f"{t('chat_amt_note', L)}\n\n"
            "---\n" + t("chat_amt_source", L)
        )

    def _answer_recommendation(self) -> str:
        L = self.lang
        step5 = self._get_step("Step 5: 加载盘点结果")
        step7 = self._get_step("Step 7: 日志关联分析")
        step9 = self._get_step("Step 9: 品类维度分析")
        lines = [t("chat_rec_title", L) + "\n"]
        anomalies = step9.get("anomaly_categories", [])
        severe = [a for a in anomalies if a.get("严重程度") == "严重异常"]
        if severe:
            lines.append(f"### {t('chat_rec_urgent', L)}")
            for a in severe:
                lines.append(f"- **{a['品类']}**（{t('kpi_variance_rate', L)} {a['差异率']}%）")
            lines.append("")
        no_log = step7.get("无日志关联", {}).get("count", 0) if isinstance(step7, dict) else 0
        if no_log > 0:
            lines.append(f"### {t('chat_rec_important', L)}")
            lines.append(f"- **{no_log}** {t('chat_rec_important_no_log', L)}")
            lines.append(f"- {t('chat_rec_important_amt', L)}")
            lines.append(f"- {t('chat_rec_important_loc', L)}")
            lines.append("")
        lines.append(f"### {t('chat_rec_process', L)}")
        lines.append(f"- {t('chat_rec_process_log', L)}")
        lines.append(f"- {t('chat_rec_process_review', L)}")
        lines.append(f"- {t('chat_rec_process_cleanup', L)}")
        lines.append(f"- {t('chat_rec_process_reconcile', L)}")
        lines.append("")
        lines.append("---")
        lines.append(t("chat_rec_source", L))
        return "\n".join(lines)

    def _answer_top_sku(self) -> str:
        L = self.lang
        if self.variance_df is None:
            return t("chat_no_data", L)
        df = self.variance_df.copy()
        diff_df = df[df["差异数量"] != 0].copy()
        diff_df["差异金额绝对值"] = diff_df["差异金额"].abs()
        top = diff_df.nlargest(10, "差异金额绝对值")
        lines = [t("chat_top_title", L) + "\n"]
        lines.append(t("chat_top_header", L))
        lines.append("|---|---|---|---|---|---|---|")
        for _, row in top.iterrows():
            lines.append(
                f"| {row.get('型号', '')} | {row.get('品类', '')} | "
                f"{row.get('系统库存数', 0)} | {row.get('复盘数', 0)} | "
                f"{row.get('差异数量', 0)} | {row.get('差异金额', 0):,.2f} | "
                f"{row.get('差异类型', '')} |"
            )
        lines.append("")
        lines.append("---")
        lines.append(t("chat_top_source", L))
        return "\n".join(lines)

    def _answer_sku_query(self, question: str) -> str:
        L = self.lang
        if self.variance_df is None:
            return t("chat_no_data", L)
        df = self.variance_df.copy()
        for word in question.lower().replace("查一下", "").replace("查", "").replace("sku", "").replace("型号", "").replace("search", "").replace("look", "").replace("model", "").split():
            if len(word) >= 3:
                matches = df[df["型号"].astype(str).str.contains(word, na=False)]
                if len(matches) > 0:
                    lines = [f"{t('chat_sku_query_title', L)} {len(matches)} {t('chat_sku_query_match', L)}\n"]
                    for _, row in matches.head(10).iterrows():
                        lines.append(
                            f"- **{row.get('型号', '')}**（{row.get('品类', '')}）："
                            f"{t('kpi_system_stock', L)} {row.get('系统库存数', 0)}，{t('chat_overview_recount', L).rstrip('：')} {row.get('复盘数', 0)}，"
                            f"{t('kpi_net_variance', L)} {row.get('差异数量', 0)}，{t('kpi_net_amount', L)} {row.get('差异金额', 0):,.2f}"
                        )
                    lines.append("")
                    lines.append("---")
                    lines.append(t("chat_sku_query_source", L))
                    return "\n".join(lines)
        return t("chat_sku_not_found", L)

    def _answer_help(self) -> str:
        L = self.lang
        return (
            f"{t('chat_help_title', L)}\n\n"
            f"- {t('chat_help_overview', L)}\n"
            f"- {t('chat_help_rate', L)}\n"
            f"- {t('chat_help_loss_gain', L)}\n"
            f"- {t('chat_help_anomaly', L)}\n"
            f"- {t('chat_help_log', L)}\n"
            f"- {t('chat_help_location', L)}\n"
            f"- {t('chat_help_noise', L)}\n"
            f"- {t('chat_help_quality', L)}\n"
            f"- {t('chat_help_amount', L)}\n"
            f"- {t('chat_help_recommend', L)}\n"
            f"- {t('chat_help_top', L)}\n"
            f"- {t('chat_help_sku', L)}\n\n"
            f"{t('chat_help_try', L)}"
        )

    def _answer_default(self, question: str) -> str:
        L = self.lang
        return (
            f"{t('chat_default_sorry', L)}「{question}」。\n\n"
            f"{t('chat_default_try', L)}\n"
            f"- {t('chat_default_q1', L)}\n"
            f"- {t('chat_default_q2', L)}\n"
            f"- {t('chat_default_q3', L)}\n"
            f"- {t('chat_default_q4', L)}\n"
            f"- {t('chat_default_q5', L)}\n"
            f"- {t('chat_default_q6', L)}"
        )


def create_ui(agent):
    """创建 Gradio Web UI — 审计级库存风险指挥舱。"""
    chat_engine = ChatEngine(history_file="data/chat_history.json")

    # ═══════════════════════════════════════════════════
    # 格式化辅助
    # ═══════════════════════════════════════════════════
    def _fmt_int(v):
        if v is None:
            return "-"
        try:
            return f"{int(v):,}"
        except (ValueError, TypeError):
            return str(v)

    def _fmt_money(v):
        if v is None:
            return "-"
        try:
            return f"{float(v):,.2f}"
        except (ValueError, TypeError):
            return str(v)

    def _pill(status):
        m = {"success": "pill-ok", "completed": "pill-ok", "error": "pill-danger",
             "failed": "pill-danger", "blocked": "pill-risk", "running": "pill-risk"}
        cls = m.get(status, "pill-ok")
        return f'<span class="status-pill {cls}">{status}</span>'

    def _render_hero(result, lang="en"):
        meta = result.get("_metadata", {}) or {}
        rid = meta.get("run_id", "") or "-"
        status = meta.get("status", "")
        duration = meta.get("duration_seconds")
        dur_str = f"{duration}s" if duration else "-"
        started = meta.get("started_at", "") or "-"
        started_short = str(started)[:19] if started != "-" else "-"
        iv = result.get("input_validation", {})
        iv_status = iv.get("summary", t("hero_validation_unavail", lang)) if iv else t("hero_validation_unavail", lang)

        return f"""<div class="audit-hero">
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div>
      <h2>{t('hero_title', lang)}</h2>
      <div class="hero-subtitle">{t('hero_subtitle', lang)}</div>
    </div>
    <span class="hero-tag">{t('hero_tag', lang)}</span>
  </div>
  <div class="hero-meta">
    <span>{t('hero_run_id', lang)}：{rid}</span>
    <span>{t('hero_status', lang)}：{_pill(status) if status else '-'}</span>
    <span>{t('hero_duration', lang)}：{dur_str}</span>
    <span>{t('hero_started', lang)}：{started_short}</span>
    <span>{t('hero_input_validation', lang)}：{iv_status}</span>
  </div>
</div>"""

    def _render_kpi_grid(result, lang="en"):
        step5 = result.get("Step 5: 加载盘点结果", {})
        step6 = result.get("Step 6: 计算差异金额", {})
        step7 = result.get("Step 7: 日志关联分析", {})
        meta = result.get("_metadata", {}) or {}
        total_sku = step5.get("total_sku", 0) or 0
        system_total = step5.get("system_total", 0) or 0
        net_var = step5.get("net_variance", 0) or 0
        var_rate = step5.get("variance_rate", 0) or 0
        net_amt = step6.get("net_variance_amount", 0) or 0
        if isinstance(step7, dict) and "无日志关联" in step7:
            no_log = step7["无日志关联"].get("count", 0)
        else:
            no_log = 0
        qg = meta.get("quality_gate", {})
        passed = qg.get("passed_count", 0)
        total_q = qg.get("total", 0)
        critical_failed = qg.get("critical_failed", 0)
        report_allowed = qg.get("report_allowed", True)
        if total_q == 0:
            checks = result.get("quality_checks", [])
            passed = sum(1 for c in checks if c.get("passed", False))
            total_q = len(checks)
        amt_color = "var(--danger)" if net_amt < 0 else "var(--ink)"
        qg_tag = f"{passed}/{total_q}" if total_q else "-"
        qg_tag += f" ⚠️{critical_failed}C" if critical_failed > 0 else ""
        report_status = f"✅ {t('kpi_report_allowed', lang)}" if report_allowed else f"⛔ {t('kpi_report_blocked', lang)}"

        return f"""<div class="kpi-grid">
  <div class="kpi-card"><div class="kpi-label">{t('kpi_total_sku', lang)}</div><div class="kpi-value">{_fmt_int(total_sku)}</div></div>
  <div class="kpi-card"><div class="kpi-label">{t('kpi_system_stock', lang)}</div><div class="kpi-value">{_fmt_int(system_total)}</div><div class="kpi-sub">{t('kpi_unit_pcs', lang)}</div></div>
  <div class="kpi-card"><div class="kpi-label">{t('kpi_net_variance', lang)}</div><div class="kpi-value">{_fmt_int(net_var)}</div><div class="kpi-sub">{t('kpi_unit_pcs', lang)}</div></div>
  <div class="kpi-card"><div class="kpi-label">{t('kpi_variance_rate', lang)}</div><div class="kpi-value">{var_rate}%</div></div>
  <div class="kpi-card"><div class="kpi-label">{t('kpi_net_amount', lang)}</div><div class="kpi-value" style="color:{amt_color}">{_fmt_money(net_amt)}</div><div class="kpi-sub">{t('kpi_currency_unit', lang)}</div></div>
  <div class="kpi-card"><div class="kpi-label">{t('kpi_no_log', lang)}</div><div class="kpi-value">{no_log}</div><div class="kpi-sub">{t('kpi_need_onsite', lang)}</div></div>
  <div class="kpi-card"><div class="kpi-label">{t('kpi_quality_gate', lang)}</div><div class="kpi-value">{qg_tag}</div></div>
  <div class="kpi-card"><div class="kpi-label">{t('kpi_report_gen', lang)}</div><div class="kpi-value" style="font-size:14px">{report_status}</div></div>
</div>"""

    def _render_risk_panel(result, lang="en"):
        meta = result.get("_metadata", {}) or {}
        status = meta.get("status", "")
        step6 = result.get("Step 6: 计算差异金额", {})
        step7 = result.get("Step 7: 日志关联分析", {})
        step9 = result.get("Step 9: 品类维度分析", {})

        if not status:
            return ""

        net_amt = step6.get("net_variance_amount", 0) or 0
        no_log_count = 0
        if isinstance(step7, dict) and "无日志关联" in step7:
            no_log_count = step7["无日志关联"].get("count", 0)
        anomalies = step9.get("anomaly_categories", [])
        severe = [a for a in anomalies if a.get("严重程度") == "严重异常"]

        parts = []
        financial_risk = t("risk_high", lang) if abs(net_amt) > 500000 else (t("risk_medium", lang) if abs(net_amt) > 100000 else t("risk_low", lang))
        explain_risk = t("risk_high", lang) if no_log_count > 50 else (t("risk_medium", lang) if no_log_count > 10 else t("risk_low", lang))
        audit_trust = t("risk_pass", lang) if status == "completed" else t("risk_incomplete", lang)

        fr_color = "var(--danger)" if financial_risk == t("risk_high", lang) else ("var(--risk)" if financial_risk == t("risk_medium", lang) else "var(--ok)")
        er_color = "var(--danger)" if explain_risk == t("risk_high", lang) else ("var(--risk)" if explain_risk == t("risk_medium", lang) else "var(--ok)")
        at_color = "var(--ok)" if audit_trust == t("risk_pass", lang) else "var(--risk)"

        parts.append(f"""<div class="audit-grid">
  <div class="stat-item"><div class="label">{t('risk_financial_impact', lang)}</div><div class="value" style="color:{fr_color}">{financial_risk}</div></div>
  <div class="stat-item"><div class="label">{t('risk_explainability', lang)}</div><div class="value" style="color:{er_color}">{explain_risk}</div></div>
  <div class="stat-item"><div class="label">{t('risk_audit_trust', lang)}</div><div class="value" style="color:{at_color}">{audit_trust}</div></div>
</div>""")

        if severe:
            names = "、".join(a["品类"] for a in severe)
            parts.append(f'<div class="danger-panel"><div class="risk-title">{t("risk_severe_title", lang)}</div><div style="font-size:13px;margin-top:4px">{names}{t("risk_severe_desc", lang)}</div></div>')
        if no_log_count > 0:
            parts.append(f'<div class="risk-panel"><div class="risk-title">{t("risk_no_log_title", lang)}</div><div style="font-size:13px;margin-top:4px">{no_log_count}{t("risk_no_log_desc", lang)}</div></div>')
        if net_amt < 0:
            parts.append(f'<div class="risk-panel"><div class="risk-title">{t("risk_net_amount_title", lang)} {_fmt_money(net_amt)} {t("kpi_currency_unit", lang)}</div><div style="font-size:13px;margin-top:4px">{t("risk_net_amount_desc_neg", lang)}</div></div>')

        return "\n".join(parts)

    def _render_capability_cards(result, lang="en"):
        step2 = result.get("Step 2: 识别噪音数据", {})
        step3 = result.get("Step 3: 选定比对基准", {})
        step7 = result.get("Step 7: 日志关联分析", {})
        noise_log = step2.get("scan_log_noise", {})
        noise_files = step2.get("noise_files", [])
        noise_count = noise_log.get("noise_count", 0) if noise_log else 0
        baseline = step3.get("selected", "")
        reason = step3.get("reason", "")
        fully = 0
        partial = 0
        no_log = 0
        if isinstance(step7, dict) and "完全可解释" in step7:
            fully = step7["完全可解释"].get("count", 0)
            partial = step7["部分可解释"].get("count", 0)
            no_log = step7["无日志关联"].get("count", 0)

        baseline_html = f"{t('cap_baseline_desc1', lang)} <strong>{baseline}</strong> {t('cap_baseline_desc2', lang)}" if baseline else t("cap_baseline_desc3", lang)
        reason_html = f" {t('cap_baseline_reason', lang)}{reason}" if reason else ""

        return f"""<div style="display:flex;gap:14px;flex-wrap:wrap">
  <div class="cap-card">
    <h4>{t('cap_noise_title', lang)}</h4>
    <p>{t('cap_noise_desc1', lang)} <strong>{noise_count}</strong> {t('cap_noise_desc2', lang)}{t('cap_noise_desc3', lang)} <strong>{len(noise_files)}</strong> {t('cap_noise_desc4', lang)}</p>
  </div>
  <div class="cap-card">
    <h4>{t('cap_baseline_title', lang)}</h4>
    <p>{baseline_html}{reason_html}</p>
  </div>
  <div class="cap-card">
    <h4>{t('cap_log_title', lang)}</h4>
    <p>{t('cap_log_desc', lang)} {t('cap_log_fully', lang)} <strong>{fully}</strong> / {t('cap_log_partial', lang)} <strong>{partial}</strong> / {t('cap_log_none', lang)} <strong>{no_log}</strong></p>
  </div>
</div>"""

    def _render_action_panel(result, lang="en"):
        step7 = result.get("Step 7: 日志关联分析", {})
        step9 = result.get("Step 9: 品类维度分析", {})
        step6 = result.get("Step 6: 计算差异金额", {})
        net_amt = step6.get("net_variance_amount", 0) or 0
        actions = []
        anomalies = step9.get("anomaly_categories", [])
        severe = [a for a in anomalies if a.get("严重程度") == "严重异常"]
        if severe:
            actions.append(f"""<div class="action-card">
  <div class="action-icon" style="background:#fee2e2;color:#991b1b">!</div>
  <div class="action-body"><h5>{t('action_review_title', lang)}</h5><p>{t('action_review_desc', lang)}</p></div>
</div>""")
        no_log_count = 0
        if isinstance(step7, dict) and "无日志关联" in step7:
            no_log_count = step7["无日志关联"].get("count", 0)
        if no_log_count > 0:
            actions.append(f"""<div class="action-card">
  <div class="action-icon" style="background:#fef3c7;color:#b45309">?</div>
  <div class="action-body"><h5>{t('action_adjust_title', lang)}</h5><p>{no_log_count}{t('action_adjust_desc', lang)}</p></div>
</div>""")
        actions.append(f"""<div class="action-card">
  <div class="action-icon" style="background:#dcfce7;color:#166534">~</div>
  <div class="action-body"><h5>{t('action_optimize_title', lang)}</h5><p>{t('action_optimize_desc', lang)}</p></div>
</div>""")
        return "\n".join(actions)

    STEP_MEANINGS_EN = {
        "Step 1": "wf_step1",
        "Step 2": "wf_step2",
        "Step 3": "wf_step3",
        "Step 4": "wf_step4",
        "Step 5": "wf_step5",
        "Step 6": "wf_step6",
        "Step 7": "wf_step7",
        "Step 8": "wf_step8",
        "Step 9": "wf_step9",
        "Step 10": "wf_step10",
    }

    def _render_workflow_timeline(result, lang="en"):
        meta = result.get("_metadata", {}) or {}
        trace = meta.get("workflow_trace") or result.get("workflow_trace", [])
        if not trace:
            return ""
        items = []
        for t_item in trace:
            step = t_item.get("step", "")
            status = t_item.get("status", "")
            dur = t_item.get("duration_ms", "")
            summary = t_item.get("summary", "")
            cls = "pill-ok" if status == "success" else ("pill-danger" if status == "error" else "pill-risk")
            short_step = step.split(":")[0] if ":" in step else step
            meaning_key = STEP_MEANINGS_EN.get(short_step, "")
            meaning = t(meaning_key, lang) if meaning_key else ""
            meaning_html = f'<span style="color:var(--muted);font-size:11px;margin-left:6px">({meaning})</span>' if meaning else ""
            items.append(f"""<div class="timeline-item">
  <div class="step-name"><span class="status-pill {cls}">{status}</span> {step}{meaning_html}</div>
  <div class="step-summary">{summary}</div>
  <div class="step-duration">{dur} ms</div>
</div>""")
        total_s = meta.get("duration_seconds")
        rid = meta.get("run_id", "")
        footer = ""
        if total_s:
            footer += f'<div style="margin-top:10px;font-size:13px;color:var(--muted);text-align:right">{t("wf_total_time", lang)} {total_s}s</div>'
        if rid:
            footer += f'<div style="font-size:12px;color:var(--muted)">{t("meta_run_id", lang)}：{rid}</div>'
        return f"""<div class="card-section">
  <h3>{t('wf_title', lang)}</h3>
  {''.join(items)}
  {footer}
</div>"""

    def _render_quality_gate(result, lang="en"):
        checks = result.get("quality_checks", [])
        meta = result.get("_metadata", {}) or {}
        qg = meta.get("quality_gate", {})
        if not checks:
            return ""
        total = len(checks)
        passed_count = qg.get("passed_count", sum(1 for c in checks if c.get("passed", False)))
        critical_failed = qg.get("critical_failed", 0)
        report_allowed = qg.get("report_allowed", critical_failed == 0)
        items = []
        for i, c in enumerate(checks, 1):
            p = c.get("passed", False)
            items.append(f"""<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #f1f5f9;font-size:13px">
  <span class="status-pill {"pill-ok" if p else "pill-danger"}">{"PASS" if p else "FAIL"}</span>
  <strong>{c.get("name","")}</strong>
  <span style="color:var(--muted)">({c.get("importance","")})</span>
  <span style="color:var(--muted);margin-left:auto;font-size:12px">{c.get("detail","")}</span>
</div>""")
        header = f'{passed_count}/{total} {t("qg_passed", lang)}'
        if critical_failed > 0:
            header += f' | ⚠️ {t("qg_critical_fail", lang)}: {critical_failed}'
        report_label = f'{t("qg_report", lang)} {"✅ " + t("qg_allowed", lang) if report_allowed else "⛔ " + t("qg_blocked", lang)}'
        header += f' | {report_label}'
        extra = ''
        if not report_allowed:
            extra = f'<div class="danger-panel"><div class="risk-title">{t("qg_blocked_detail_title", lang)}</div><div style="font-size:13px;margin-top:4px">{t("qg_blocked_detail_desc", lang)}</div></div>'
        return f"""<div class="card-section">
  <h3>{t('qg_title', lang)} <span class="status-pill {"pill-ok" if report_allowed else "pill-danger"}">{header}</span></h3>
  {extra}
  {''.join(items)}
</div>"""

    def _render_input_validation(result, lang="en"):
        iv = result.get("input_validation")
        if not iv:
            return f"""<div class="card-section">
  <h3>{t('iv_title', lang)}</h3>
  <div style="font-size:13px;color:var(--muted)">{t('iv_unavail', lang)}</div>
</div>"""
        passed = iv.get("passed", False)
        matched = iv.get("matched_files", [])
        missing = iv.get("missing_required", [])
        unexpected = iv.get("unexpected_files", [])
        summary = iv.get("summary", "")
        header = f'<span class="status-pill {"pill-ok" if passed else "pill-danger"}">{t("iv_passed", lang) if passed else t("iv_not_passed", lang)}</span>'
        lines = [f"""<div class="card-section">
  <h3>{t('iv_title', lang)} {header}</h3>
  <div style="font-size:13px">{summary}</div>"""]
        if matched:
            lines.append(f'<div style="margin-top:8px;font-size:13px;color:var(--muted)">{t("iv_matched_files", lang)} {len(matched)}</div>')
        if missing:
            lines.append(f'<div style="margin-top:8px;font-size:13px;color:var(--danger)">{t("iv_missing_files", lang)} {", ".join(missing)}</div>')
        if unexpected:
            lines.append(f'<div style="margin-top:8px;font-size:13px;color:var(--risk)">{t("iv_unexpected_files", lang)} {", ".join(unexpected)}</div>')
        lines.append("</div>")
        return "\n".join(lines)

    def _render_deliverables(result, lang="en"):
        meta = result.get("_metadata", {}) or {}
        dp = meta.get("deliverable_package", {})
        if dp:
            items = []
            for key, info in dp.items():
                exists_mark = "✅" if info.get("exists") else "❌"
                path = info.get("path", "")
                purpose = info.get("purpose", "")
                items.append(f'<div style="margin:4px 0;font-family:monospace;font-size:13px">{exists_mark} <strong>{key}</strong>: {path}<br><span style="color:var(--muted);font-size:12px;font-family:sans-serif"> → {purpose}</span></div>')
            content = "\n".join(items)
        else:
            dl = result.get("Step 10: 生成交付物", {})
            xlsx = dl.get("xlsx_path", t("del_not_generated", lang))
            md = dl.get("md_path", t("del_not_generated", lang))
            content = f"<div>{t('del_xlsx', lang)}: {xlsx}<br>{t('del_report', lang)}: {md}</div>"
        return f"""<div class="card-section">
  <h3>{t('del_title', lang)}</h3>
  <div style="font-size:13px;color:var(--muted);margin-bottom:8px">{t('del_desc', lang)}</div>
  <div style="background:#f8fafc;border-radius:8px;padding:10px;border:1px solid var(--line)">
    {content}
  </div>
  <div style="font-size:12px;color:var(--muted);margin-top:8px">{t('del_goto_qa', lang)}</div>
</div>"""

    def _render_audit_summary(result, lang="en"):
        meta = result.get("_metadata", {}) or {}
        has_data = bool(meta.get("run_id"))
        if not has_data:
            return f"""<div class="card-section">
  <h3>{t('audit_title', lang)}</h3>
  <div style="font-size:13px;color:var(--muted)">{t('audit_empty', lang)}</div>
</div>"""
        return f"""<div class="card-section">
  <h3>{t('audit_title', lang)}</h3>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:10px">
    <div style="background:#f8fafc;border-radius:10px;padding:12px;border:1px solid var(--line)">
      <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em">{t('audit_fact_label', lang)}</div>
      <div style="font-size:14px;font-weight:700;color:var(--ok);margin-top:4px">{t('audit_fact_value', lang)}</div>
      <div style="font-size:12px;color:var(--muted);margin-top:4px">{t('audit_fact_desc', lang)}</div>
    </div>
    <div style="background:#f8fafc;border-radius:10px;padding:12px;border:1px solid var(--line)">
      <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em">{t('audit_llm_label', lang)}</div>
      <div style="font-size:14px;font-weight:700;color:var(--accent);margin-top:4px">{t('audit_llm_value', lang)}</div>
      <div style="font-size:12px;color:var(--muted);margin-top:4px">{t('audit_llm_desc', lang)}</div>
    </div>
    <div style="background:#f8fafc;border-radius:10px;padding:12px;border:1px solid var(--line)">
      <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em">{t('audit_data_label', lang)}</div>
      <div style="font-size:14px;font-weight:700;color:var(--ink);margin-top:4px">{t('audit_data_value', lang)}</div>
      <div style="font-size:12px;color:var(--muted);margin-top:4px">{t('audit_data_desc', lang)}</div>
    </div>
  </div>
</div>"""

    def _render_run_metadata(result, lang="en"):
        meta = result.get("_metadata", {}) or {}
        rid = meta.get("run_id", "")
        if not rid:
            return ""
        status = meta.get("status", "")
        duration = meta.get("duration_seconds")
        dur_str = f"{duration}s" if duration else "-"
        started = meta.get("started_at", "") or "-"
        finished = meta.get("finished_at", "") or "-"
        version = meta.get("workflow_version", "")
        input_dir = meta.get("input_dir", "")
        output_dir = meta.get("output_dir", "")
        iv = result.get("input_validation", {})
        iv_summary = iv.get("summary", t("hero_validation_unavail", lang)) if iv else t("hero_validation_unavail", lang)
        return f"""<div class="card-section">
  <h3>{t('meta_title', lang)}</h3>
  <div class="audit-grid">
    <div class="stat-item"><div class="label">{t('meta_run_id', lang)}</div><div class="value" style="font-family:monospace;font-size:14px">{rid}</div></div>
    <div class="stat-item"><div class="label">{t('meta_status', lang)}</div><div class="value">{_pill(status) if status else "-"}</div></div>
    <div class="stat-item"><div class="label">{t('meta_total_time', lang)}</div><div class="value">{dur_str}</div></div>
    <div class="stat-item"><div class="label">{t('meta_version', lang)}</div><div class="value" style="font-size:14px">{version or "-"}</div></div>
    <div class="stat-item"><div class="label">{t('meta_started', lang)}</div><div class="value" style="font-size:13px">{str(started)[:19]}</div></div>
    <div class="stat-item"><div class="label">{t('meta_finished', lang)}</div><div class="value" style="font-size:13px">{str(finished)[:19] if finished != "-" else "-"}</div></div>
    <div class="stat-item"><div class="label">{t('meta_input_dir', lang)}</div><div class="value" style="font-size:13px;font-family:monospace">{input_dir or "-"}</div></div>
    <div class="stat-item"><div class="label">{t('meta_output_dir', lang)}</div><div class="value" style="font-size:13px;font-family:monospace">{output_dir or "-"}</div></div>
    <div class="stat-item"><div class="label">{t('meta_input_check', lang)}</div><div class="value" style="font-size:13px">{iv_summary}</div></div>
  </div>
</div>"""

    def _build_input_audit_df(result, lang="en"):
        meta = result.get("_metadata", {}) or {}
        input_files = meta.get("input_files", []) or []
        if not input_files:
            return pd.DataFrame(columns=[t("audit_tbl_filename", lang), t("audit_tbl_size", lang), t("audit_tbl_hash", lang), t("audit_tbl_modified", lang), t("audit_tbl_status", lang)])
        rows = []
        for f in input_files:
            error = f.get("error")
            if error:
                status_str = f"{t('audit_tbl_error', lang)} {error}"
            else:
                status_str = t("audit_tbl_collected", lang)
            size_bytes = f.get("size_bytes")
            if size_bytes is not None and size_bytes != "-":
                try:
                    sb = int(size_bytes)
                    if sb < 1024:
                        size_display = f"{sb} B"
                    elif sb < 1024 * 1024:
                        size_display = f"{sb/1024:.1f} KB"
                    else:
                        size_display = f"{sb/1024/1024:.1f} MB"
                except (ValueError, TypeError):
                    size_display = str(size_bytes)
            else:
                size_display = "-"
            rows.append({
                t("audit_tbl_filename", lang): f.get("name", "-"),
                t("audit_tbl_size", lang): size_display,
                t("audit_tbl_hash", lang): (f.get("sha256", "") or "-")[:12],
                t("audit_tbl_modified", lang): (f.get("modified_at", "") or "-")[:19],
                t("audit_tbl_status", lang): status_str,
            })
        return pd.DataFrame(rows)

    def _empty_df(lang="en"):
        return pd.DataFrame(columns=[t("audit_tbl_filename", lang), t("audit_tbl_size", lang), t("audit_tbl_hash", lang), t("audit_tbl_modified", lang), t("audit_tbl_status", lang)])

    # ═══════════════════════════════════════════════════
    # Plotly 图表辅助
    # ═══════════════════════════════════════════════════
    def _empty_figure(title):
        fig = go.Figure()
        fig.add_annotation(text=title, x=0.5, y=0.5, showarrow=False,
                           font=dict(size=14, color="#94a3b8"))
        fig.update_layout(
            xaxis=dict(visible=False), yaxis=dict(visible=False),
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=10, r=10, t=10, b=10),
            height=280,
        )
        return fig

    def _build_category_plot(result, lang="en"):
        step9 = result.get("Step 9: 品类维度分析", {})
        categories = step9.get("categories", [])
        if not categories:
            return _empty_figure(t("plot_empty_analysis", lang))
        df = pd.DataFrame(categories)
        df = df.sort_values("差异率", ascending=True)
        colors = []
        for r in df["差异率"]:
            if r > 10:
                colors.append("#991b1b")
            elif r > 5:
                colors.append("#b45309")
            else:
                colors.append("#2563eb")
        fig = go.Figure(go.Bar(
            x=df["差异率"], y=df["品类"],
            orientation="h", marker_color=colors,
            text=df["差异率"].apply(lambda x: f"{x}%"),
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>" + t("plot_category_x", lang) + "：%{x}%<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text=t("plot_category_title", lang), font=dict(size=14, color="#0f172a")),
            xaxis=dict(title=t("plot_category_x", lang), gridcolor="#f1f5f9", zeroline=False),
            yaxis=dict(title=t("plot_category_y", lang), autorange="reversed"),
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=10, r=40, t=40, b=10),
            height=320,
            font=dict(family="-apple-system, BlinkMacSystemFont, sans-serif"),
        )
        return fig

    def _build_log_correlation_plot(result, lang="en"):
        step7 = result.get("Step 7: 日志关联分析", {})
        if not isinstance(step7, dict) or "完全可解释" not in step7:
            return _empty_figure(t("plot_log_empty", lang))
        labels = [t("plot_log_fully", lang), t("plot_log_partial", lang), t("plot_log_none", lang)]
        keys = ["完全可解释", "部分可解释", "无日志关联"]
        values = [step7[k].get("count", 0) for k in keys]
        amounts = [step7[k].get("amount", 0) for k in keys]
        if sum(values) == 0:
            return _empty_figure(t("plot_log_empty", lang))
        colors = ["#166534", "#b45309", "#991b1b"]
        fig = go.Figure(go.Pie(
            labels=labels, values=values, hole=0.62,
            marker_colors=colors,
            textinfo="label+percent",
            textfont=dict(size=12, color="#0f172a"),
            hovertemplate="<b>%{label}</b><br>SKU: %{value}<br>" + t("kpi_net_amount", lang) + "：%{customdata:,.2f}<extra></extra>",
            customdata=[[a] for a in amounts],
        ))
        fig.update_layout(
            title=dict(text=t("plot_log_title", lang), font=dict(size=14, color="#0f172a")),
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=10, r=10, t=40, b=10),
            height=320,
            font=dict(family="-apple-system, BlinkMacSystemFont, sans-serif"),
            legend=dict(orientation="h", y=-0.12),
        )
        return fig

    def _build_amount_plot(result, lang="en"):
        step6 = result.get("Step 6: 计算差异金额", {})
        if not step6:
            return _empty_figure(t("plot_amount_empty", lang))
        loss = abs(step6.get("total_loss_amount", 0) or 0)
        gain = step6.get("total_gain_amount", 0) or 0
        net = step6.get("net_variance_amount", 0) or 0
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name=t("plot_amount_shortage", lang), x=[t("plot_amount_shortage", lang)], y=[loss],
            marker_color="#991b1b",
            text=f"{loss:,.2f}", textposition="outside",
            hovertemplate=t("plot_amount_shortage", lang) + "：%{y:,.2f}<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            name=t("plot_amount_surplus", lang), x=[t("plot_amount_surplus", lang)], y=[gain],
            marker_color="#166534",
            text=f"{gain:,.2f}", textposition="outside",
            hovertemplate=t("plot_amount_surplus", lang) + "：%{y:,.2f}<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            name=t("plot_amount_net", lang), x=[t("plot_amount_net", lang)], y=[abs(net)],
            marker_color="#2563eb" if net >= 0 else "#991b1b",
            text=f"{net:,.2f}", textposition="outside",
            hovertemplate=t("plot_amount_net", lang) + "：%{y:,.2f}<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text=t("plot_amount_title", lang), font=dict(size=14, color="#0f172a")),
            yaxis=dict(title=t("plot_amount_y", lang), gridcolor="#f1f5f9", zeroline=False),
            plot_bgcolor="white", paper_bgcolor="white",
            barmode="group",
            margin=dict(l=10, r=30, t=40, b=10),
            height=320,
            font=dict(family="-apple-system, BlinkMacSystemFont, sans-serif"),
            legend=dict(orientation="h", y=-0.2),
        )
        return fig

    def _build_location_plot(result, lang="en"):
        step8 = result.get("Step 8: 库位状态校验", {})
        dist = step8.get("status_distribution", {})
        if not dist:
            return _empty_figure(t("plot_location_empty", lang))
        label_keys = list(dist.keys())
        values = list(dist.values())
        if sum(values) == 0:
            return _empty_figure(t("plot_location_no_data", lang))
        label_map = {
            "启用": t("plot_location_active", lang),
            "已停用": t("plot_location_disabled", lang),
            "维修中": t("plot_location_maintenance", lang),
            "未知": t("plot_location_unknown", lang),
        }
        labels = [label_map.get(k, k) for k in label_keys]
        color_map = {"启用": "#166534", "已停用": "#b45309", "维修中": "#991b1b", "未知": "#94a3b8"}
        colors = [color_map.get(k, "#94a3b8") for k in label_keys]
        fig = go.Figure(go.Pie(
            labels=labels, values=values, hole=0.62,
            marker_colors=colors,
            textinfo="label+value",
            textfont=dict(size=12, color="#0f172a"),
            hovertemplate="<b>%{label}</b><br>SKU: %{value}<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text=t("plot_location_title", lang), font=dict(size=14, color="#0f172a")),
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=10, r=10, t=40, b=10),
            height=320,
            font=dict(family="-apple-system, BlinkMacSystemFont, sans-serif"),
            legend=dict(orientation="h", y=-0.12),
        )
        return fig

    def _build_top_sku_df(lang="en"):
        metadata = getattr(agent, 'analysis_result', {}).get('_metadata', {})
        top_skus = metadata.get('top_variance_skus', [])
        col_model = t("plot_sku_model", lang)
        col_category = t("plot_sku_category", lang)
        col_sys = t("plot_sku_sys_stock", lang)
        col_recount = t("plot_sku_recount", lang)
        col_diff_qty = t("plot_sku_diff_qty", lang)
        col_diff_amt = t("plot_sku_diff_amt", lang)
        col_diff_type = t("plot_sku_diff_type", lang)
        if top_skus:
            rows = []
            for s in top_skus:
                rows.append({
                    col_model: s.get("sku", ""),
                    col_category: s.get("category", ""),
                    col_sys: s.get("system_stock", 0),
                    col_recount: s.get("recount_stock", 0),
                    col_diff_qty: s.get("variance_qty", 0),
                    col_diff_amt: s.get("variance_amount", 0),
                    col_diff_type: s.get("variance_type", ""),
                })
            return pd.DataFrame(rows)
        if agent._variance_df is None:
            return pd.DataFrame(columns=[col_model, col_category, col_sys, col_recount, col_diff_qty, col_diff_amt, col_diff_type])
        df = agent._variance_df.copy()
        diff_df = df[df["差异数量"] != 0].copy()
        if len(diff_df) == 0:
            return pd.DataFrame(columns=[col_model, col_category, col_sys, col_recount, col_diff_qty, col_diff_amt, col_diff_type])
        diff_df["|差异金额|"] = diff_df["差异金额"].abs()
        top = diff_df.nlargest(10, "|差异金额|")
        result = top[["型号", "品类", "系统库存数", "复盘数", "差异数量", "差异金额", "差异类型"]].copy()
        result["差异金额"] = result["差异金额"].round(2)
        result.columns = [col_model, col_category, col_sys, col_recount, col_diff_qty, col_diff_amt, col_diff_type]
        return result

    # ═══════════════════════════════════════════════════
    # UI 回调函数
    # ═══════════════════════════════════════════════════
    def run_analysis(input_dir, lang="en"):
        chat_engine.lang = lang
        if not input_dir or not Path(input_dir).exists():
            empty = _empty_df(lang)
            empty_fig = _empty_figure(t("btn_analyze", lang))
            return ("", "", "", "", "", "", "", "", "", "", "",
                    empty, empty_fig, empty_fig, empty_fig, empty_fig, empty)

        output_dir = str(Path(input_dir).parent / "output")
        result = agent.run_workflow(input_dir, output_dir)
        chat_engine.load_analysis(result, agent._variance_df)

        hero = _render_hero(result, lang)
        kpi = _render_kpi_grid(result, lang)
        risk = _render_risk_panel(result, lang)
        cap = _render_capability_cards(result, lang)
        action = _render_action_panel(result, lang)

        audit_summary = _render_audit_summary(result, lang)
        run_metadata = _render_run_metadata(result, lang)
        timeline = _render_workflow_timeline(result, lang)
        quality = _render_quality_gate(result, lang)
        input_val = _render_input_validation(result, lang)
        deliverables = _render_deliverables(result, lang)

        input_audit_df = _build_input_audit_df(result, lang)

        category_fig = _build_category_plot(result, lang)
        log_fig = _build_log_correlation_plot(result, lang)
        amount_fig = _build_amount_plot(result, lang)
        location_fig = _build_location_plot(result, lang)
        top_sku_df = _build_top_sku_df(lang)

        return (hero, kpi, risk, cap, action,
                audit_summary, run_metadata,
                timeline, quality, input_val, deliverables,
                input_audit_df,
                category_fig, log_fig, amount_fig, location_fig, top_sku_df)

    def chat_response(message, history, lang="en"):
        import time
        chat_engine.lang = lang
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": "..."})
        yield history, ""
        time.sleep(0.3)
        response = chat_engine.answer(message)
        chat_engine.add_to_history("user", message)
        chat_engine.add_to_history("assistant", response)
        history[-1] = {"role": "assistant", "content": response}
        yield history, ""

    def clear_chat():
        chat_engine.clear_history()
        return [], ""

    def export_chat(lang="en"):
        filepath = chat_engine.save_markdown()
        return f"{t('chat_export_saved', lang)} `{filepath}`"

    def _start_mock_server(port: int = 0) -> str:
        class MockHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/v1/models":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "object": "list",
                        "data": [{"id": "mock-llm", "object": "model", "created": 1234567890, "owned_by": "mock"}]
                    }).encode())

            def do_POST(self):
                if self.path == "/v1/chat/completions":
                    content_len = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(content_len)) if content_len else {}
                    prompt = body.get("messages", [{}])[-1].get("content", "")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    mock_response = (
                        "这是 Mock LLM 响应。请以调用方提供的结构化事实区块为准；"
                        "本 Mock 不生成任何固定 SKU、金额或品类事实。"
                    )
                    resp = {
                        "id": "mock-cmpl", "object": "chat.completion",
                        "created": int(time.time()), "model": "mock-llm",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": mock_response}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": len(prompt), "completion_tokens": len(mock_response), "total_tokens": len(prompt) + len(mock_response)}
                    }
                    self.wfile.write(json.dumps(resp).encode())

            def log_message(self, fmt, *args):
                pass

        server = HTTPServer(("127.0.0.1", port), MockHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return f"http://127.0.0.1:{port}/v1"

    def generate_report(mode: str = "demo", lang="en"):
        L = lang
        if not chat_engine.initialized:
            return t("rpt_not_run", L)
        meta_output = "--"

        if mode == "demo":
            start = time.time()
            report = agent.report_generator.generate_report(agent.analysis_result, demo_mode=True)
            elapsed = time.time() - start
            meta_output = f"**{t('rpt_meta_mode', L)}**: {t('rpt_mode_demo_label', L)} | **{t('rpt_meta_time', L)}**: {elapsed:.2f}s"

        elif mode == "mock":
            mock_url = _start_mock_server(0)
            old_url = os.environ.get("LLM_BASE_URL", "")
            old_model = os.environ.get("LLM_MODEL", "")
            os.environ["LLM_BASE_URL"] = mock_url
            os.environ["LLM_MODEL"] = "mock-llm"
            os.environ["LLM_STREAMING"] = "false"
            try:
                start = time.time()
                report = agent.report_generator.generate_report(agent.analysis_result)
                elapsed = time.time() - start
                meta_output = f"**{t('rpt_meta_mode', L)}**: Mock LLM | **{t('rpt_meta_time', L)}**: {elapsed:.2f}s | **{t('rpt_meta_endpoint', L)}**: {mock_url}"
            finally:
                if old_url:
                    os.environ["LLM_BASE_URL"] = old_url
                else:
                    os.environ.pop("LLM_BASE_URL", None)
                if old_model:
                    os.environ["LLM_MODEL"] = old_model
                else:
                    os.environ.pop("LLM_MODEL", None)
                os.environ.pop("LLM_STREAMING", None)

        else:
            base_url = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
            h = check_llm_health(base_url)
            if not h["reachable"]:
                return (
                    f"**{t('llm_unreachable_title', L).lstrip('#').strip()}**\n\n"
                    f"- **{t('llm_check_endpoint', L).strip('-*:')}**: `{h['base_url']}`\n"
                    f"- **{t('llm_unreachable_error', L).strip('-*:')}**: {h.get('error', '')}\n\n"
                    f"{t('llm_unreachable_hint', L)} `{base_url}`\n\n"
                    f"{t('llm_unreachable_demo', L)}"
                )
            start = time.time()
            report = agent.report_generator.generate_report(agent.analysis_result)
            elapsed = time.time() - start
            model = os.getenv("LLM_MODEL", "local-model")
            meta_output = f"**{t('rpt_meta_mode', L)}**: {t('rpt_mode_real_label', L)} | **{t('rpt_meta_time', L)}**: {elapsed:.2f}s | **{t('rpt_meta_model', L)}**: {model} | **{t('rpt_meta_endpoint', L)}**: {base_url}"

        # 保存报告
        out_path = Path("data/output/管理层摘要报告.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")

        report += f"\n\n---\n> {meta_output}\n> {t('rpt_saved', L)} `data/output/管理层摘要报告.md`"
        return report

    def check_llm(lang="en"):
        L = lang
        base_url = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
        h = check_llm_health(base_url)
        if h["reachable"]:
            models = ", ".join(h["models"]) if h["models"] else ""
            return (
                f"**{t('llm_check_title', L).lstrip('#').strip()}**\n\n"
                f"- **{t('llm_check_endpoint', L).strip('-*:')}**: `{h['base_url']}`\n"
                f"- **{t('llm_check_models', L).strip('-*:')}**: {models}\n\n"
                f"{t('llm_check_ok', L)}"
            )
        else:
            return (
                f"**{t('llm_unreachable_title', L).lstrip('#').strip()}**\n\n"
                f"- **{t('llm_check_endpoint', L).strip('-*:')}**: `{h['base_url']}`\n"
                f"- **{t('llm_unreachable_error', L).strip('-*:')}**: {h.get('error', '')}\n\n"
                f"{t('llm_unreachable_hint2', L)}"
            )

    # ═══════════════════════════════════════════════════
    # 构建 UI
    # ═══════════════════════════════════════════════════
    with gr.Blocks(title="InventoryDoc Agent") as ui:
        lang_state = gr.State("en")

        with gr.Tabs():
            # ── Command Center ──
            with gr.TabItem(t("tab_command", "en"), id="tab_command"):
                input_dir = gr.Textbox(
                    label=t("input_dir_label", "en"),
                    placeholder=t("input_dir_placeholder", "en"),
                    value="data/input",
                )
                run_btn = gr.Button(t("btn_analyze", "en"), variant="primary")

                hero_output = gr.HTML()
                kpi_output = gr.HTML()
                risk_output = gr.HTML()
                capability_output = gr.HTML()
                action_output = gr.HTML()

            # ── Risk Visualization ──
            with gr.TabItem(t("tab_risk_viz", "en"), id="tab_risk_viz"):
                gr.HTML(f"""
                <div class="card-section" style="margin-bottom:10px">
                  <h3>{t('rviz_title', 'en')}</h3>
                  <div style="font-size:13px;color:var(--muted)">
                    {t('rviz_desc', 'en')}
                  </div>
                </div>""")
                with gr.Row():
                    with gr.Column(scale=1):
                        category_plot = gr.Plot(label=t("plot_category_title", "en"))
                        log_plot = gr.Plot(label=t("plot_log_title", "en"))
                    with gr.Column(scale=1):
                        amount_plot = gr.Plot(label=t("plot_amount_title", "en"))
                        location_plot = gr.Plot(label=t("plot_location_title", "en"))
                top_sku_table = gr.DataFrame(label=t("plot_top_sku_label", "en"))

            # ── Audit Trail ──
            with gr.TabItem(t("tab_audit", "en"), id="tab_audit"):
                audit_summary_output = gr.HTML()
                run_metadata_output = gr.HTML()
                input_validation_output = gr.HTML()
                input_audit_output = gr.DataFrame(label=t("iv_title", "en"))
                workflow_timeline_output = gr.HTML()
                quality_gate_output = gr.HTML()
                deliverables_output = gr.HTML()

            # ── Management Report ──
            with gr.TabItem(t("tab_report", "en"), id="tab_report"):
                gr.HTML(f"""
<div class="card-section">
  <h3>{t('rpt_section1_title', 'en')}</h3>
  <div style="font-size:13px;color:var(--muted);margin-bottom:10px">
    {t('rpt_section1_desc', 'en')}
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px">
    <span class="boundary-badge">{t('rpt_badge_rocm', 'en')}</span>
    <span class="boundary-badge">{t('rpt_badge_api', 'en')}</span>
    <span class="boundary-badge">{t('rpt_badge_endpoint', 'en')}：http://localhost:8000/v1</span>
  </div>
</div>

<div class="card-section">
  <h3>{t('rpt_section2_title', 'en')}</h3>
  <div style="font-size:13px;color:var(--muted);margin-bottom:10px">
    {t('rpt_section2_desc', 'en')}
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
    <span class="status-pill pill-ok">{t('rpt_mode_demo', 'en')}</span>
    <span class="status-pill pill-ok">{t('rpt_mode_mock', 'en')}</span>
    <span class="status-pill pill-risk">{t('rpt_mode_real', 'en')}</span>
  </div>
</div>""")

                report_mode = gr.Radio(
                    choices=[
                        (t("rpt_mode_demo_label", "en"), "demo"),
                        (t("rpt_mode_mock_label", "en"), "mock"),
                        (t("rpt_mode_real_label", "en"), "real"),
                    ],
                    value="demo",
                    label=t("rpt_mode_label", "en"),
                )
                with gr.Row():
                    generate_report_btn = gr.Button(t("rpt_btn_generate", "en"), variant="primary", scale=2)
                    check_llm_btn = gr.Button(t("rpt_btn_check", "en"), variant="secondary", scale=1)
                report_output = gr.Markdown()

                gr.HTML(f"""
<div class="card-section">
  <h3>{t('rpt_section3_title', 'en')}</h3>
  <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;font-size:13px">
    <div style="background:#f8fafc;border-radius:10px;padding:14px;border:1px solid var(--line)">
      <div style="font-weight:700;color:var(--ok);margin-bottom:6px">{t('rpt_boundary_fact_title', 'en')}</div>
      <div style="color:var(--muted);line-height:1.6">{t('rpt_boundary_fact_desc', 'en')}</div>
    </div>
    <div style="background:#f8fafc;border-radius:10px;padding:14px;border:1px solid var(--line)">
      <div style="font-weight:700;color:var(--accent);margin-bottom:6px">{t('rpt_boundary_llm_title', 'en')}</div>
      <div style="color:var(--muted);line-height:1.6">{t('rpt_boundary_llm_desc', 'en')}</div>
    </div>
    <div style="background:#f8fafc;border-radius:10px;padding:14px;border:1px solid var(--line)">
      <div style="font-weight:700;color:var(--ink);margin-bottom:6px">{t('rpt_boundary_data_title', 'en')}</div>
      <div style="color:var(--muted);line-height:1.6">{t('rpt_boundary_data_desc', 'en')}</div>
    </div>
    <div style="background:#f8fafc;border-radius:10px;padding:14px;border:1px solid var(--line)">
      <div style="font-weight:700;color:var(--ink);margin-bottom:6px">{t('rpt_boundary_nosys_title', 'en')}</div>
      <div style="color:var(--muted);line-height:1.6">{t('rpt_boundary_nosys_desc', 'en')}</div>
    </div>
  </div>
</div>""")

                generate_report_btn.click(generate_report, inputs=[report_mode, lang_state], outputs=[report_output])
                check_llm_btn.click(check_llm, inputs=[lang_state], outputs=[report_output])

            # ── Follow-up Q&A ──
            with gr.TabItem(t("tab_qa", "en"), id="tab_qa"):
                gr.HTML(f"""
                <div class="card-section" style="margin-bottom:10px">
                  <h3>{t('qa_title', 'en')}</h3>
                  <div style="font-size:13px;color:var(--muted)">
                    {t('qa_desc', 'en')}
                  </div>
                  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
                    <span class="status-pill pill-ok">{t('qa_hint_overview', 'en')}</span>
                    <span class="status-pill pill-ok">{t('qa_hint_rate', 'en')}</span>
                    <span class="status-pill pill-ok">{t('qa_hint_category', 'en')}</span>
                    <span class="status-pill pill-ok">{t('qa_hint_log', 'en')}</span>
                    <span class="status-pill pill-ok">{t('qa_hint_no_log', 'en')}</span>
                    <span class="status-pill pill-ok">{t('qa_hint_top', 'en')}</span>
                    <span class="status-pill pill-ok">{t('qa_hint_advice', 'en')}</span>
                    <span class="status-pill pill-ok">{t('qa_hint_sku', 'en')}</span>
                  </div>
                </div>""")

                chatbot = gr.Chatbot(
                    height=520,
                    label=t("qa_chat_label", "en"),
                    value=chat_engine.get_history(),
                    render_markdown=True,
                )
                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder=t("qa_placeholder", "en"),
                        label="",
                        scale=8,
                    )
                    send_btn = gr.Button(t("qa_btn_send", "en"), variant="primary", scale=1)
                    export_btn = gr.Button(t("qa_btn_export", "en"), variant="secondary", scale=1)
                    clear_btn = gr.Button(t("qa_btn_clear", "en"), variant="stop", scale=1)

                export_status = gr.Markdown()

                send_btn.click(chat_response, [msg_input, chatbot, lang_state], [chatbot, msg_input])
                msg_input.submit(chat_response, [msg_input, chatbot, lang_state], [chatbot, msg_input])
                export_btn.click(export_chat, inputs=[lang_state], outputs=[export_status])
                clear_btn.click(clear_chat, outputs=[chatbot, msg_input])

            # ── About ──
            with gr.TabItem(t("tab_about", "en"), id="tab_about"):
                gr.HTML(f"""
<div class="card-section">
  <h3>{t('about_positioning_title', 'en')}</h3>
  <div style="font-size:13px;color:var(--muted);line-height:1.7">
    {t('about_positioning_desc', 'en')}
  </div>
</div>

<div class="card-section">
  <h3>{t('about_workflow_title', 'en')}</h3>
  <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;font-size:13px">
    <div>{t('about_step1', 'en')}</div>
    <div>{t('about_step2', 'en')}</div>
    <div>{t('about_step3', 'en')}</div>
    <div>{t('about_step4', 'en')}</div>
    <div>{t('about_step5', 'en')}</div>
    <div>{t('about_step6', 'en')}</div>
    <div>{t('about_step7', 'en')}</div>
    <div>{t('about_step8', 'en')}</div>
    <div>{t('about_step9', 'en')}</div>
    <div>{t('about_step10', 'en')}</div>
  </div>
</div>

<div class="card-section">
  <h3>{t('about_diff_title', 'en')}</h3>
  <div style="display:flex;gap:14px;flex-wrap:wrap">
    <div class="cap-card"><h4>{t('about_diff_noise_title', 'en')}</h4><p>{t('about_diff_noise_desc', 'en')}</p></div>
    <div class="cap-card"><h4>{t('about_diff_baseline_title', 'en')}</h4><p>{t('about_diff_baseline_desc', 'en')}</p></div>
    <div class="cap-card"><h4>{t('about_diff_log_title', 'en')}</h4><p>{t('about_diff_log_desc', 'en')}</p></div>
  </div>
</div>

<div class="card-section">
  <h3>{t('about_gov_title', 'en')}</h3>
  <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;font-size:13px;color:var(--muted)">
    <div><strong>{t('about_gov_input', 'en')}</strong> — {t('about_gov_input_desc', 'en')}</div>
    <div><strong>{t('about_gov_audit', 'en')}</strong> — {t('about_gov_audit_desc', 'en')}</div>
    <div><strong>{t('about_gov_quality', 'en')}</strong> — {t('about_gov_quality_desc', 'en')}</div>
    <div><strong>{t('about_gov_evidence', 'en')}</strong> — {t('about_gov_evidence_desc', 'en')}</div>
  </div>
</div>

<div class="card-section">
  <h3>{t('about_gpu_title', 'en')}</h3>
  <div style="font-size:13px;color:var(--muted);line-height:1.7">
    {t('about_gpu_desc', 'en')}
  </div>
</div>

<div class="card-section">
  <h3>{t('about_security_title', 'en')}</h3>
  <div style="font-size:13px;color:var(--muted)">
    {t('about_security_desc', 'en')}
  </div>
</div>""")

        # ── 统一绑定运行按钮 ──
        run_btn.click(
            run_analysis,
            [input_dir, lang_state],
            [
                hero_output, kpi_output, risk_output, capability_output, action_output,
                audit_summary_output, run_metadata_output,
                workflow_timeline_output, quality_gate_output, input_validation_output,
                deliverables_output, input_audit_output,
                category_plot, log_plot, amount_plot, location_plot, top_sku_table,
            ],
        )

    # CSS 已导出为模块常量，调用方应使用 ui.launch(..., css=APP_CSS)
    return ui
