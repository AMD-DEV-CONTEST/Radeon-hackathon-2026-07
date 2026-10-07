"""Bloomberg Terminal-style reusable UI components.

All HTML is injected via st.markdown(..., unsafe_allow_html=True).
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st


# ─────────────────────────────────────────────────────────────────────────────
# CSS loader
# ─────────────────────────────────────────────────────────────────────────────

def load_css() -> None:
    """Inject the FinVeritas CSS into the Streamlit app."""
    css_path = Path(__file__).parent / "styles.css"
    if css_path.exists():
        css = css_path.read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def inject_theme_vars(font_scale: float = 1.0, light_mode: bool = False) -> None:
    """Inject font scale + optional light-mode CSS override."""
    s = round(max(0.8, min(1.4, font_scale)), 1)

    def px(base: float) -> str:
        return f"calc({s} * {base}px) !important"

    font_css = f"""<style>
    /* ── Streamlit native elements ── */
    .stMarkdown p, .stMarkdown li, .stMarkdown span,
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] span,
    [data-testid="stText"], p, li {{ font-size: {px(13)}; }}

    .stTextInput input, .stTextArea textarea, .stNumberInput input,
    .stSelectbox [data-baseweb="select"] span {{ font-size: {px(12)}; }}

    .stTextInput label, .stTextArea label, .stSelectbox label,
    .stNumberInput label, .stSlider label, .stCheckbox label,
    .stRadio label {{ font-size: {px(11)}; }}

    [data-testid="stSidebar"] .stRadio label {{ font-size: {px(12)}; }}
    [data-testid="stSidebar"] .stTextInput input {{ font-size: {px(11)}; }}
    [data-testid="stSidebar"] .stTextInput label {{ font-size: {px(9)}; }}

    .stButton > button, .stDownloadButton > button,
    [data-testid="stDownloadButton"] > button {{ font-size: {px(11)}; }}

    [data-testid="stTabs"] [role="tab"] p {{ font-size: {px(11)}; }}
    [data-testid="stExpander"] summary > p {{ font-size: {px(11)}; }}
    [data-testid="stAlert"] p {{ font-size: {px(12)}; }}

    [data-testid="stFileUploaderDropzone"] small,
    [data-testid="stFileUploadDropzone"] small {{ font-size: {px(10)}; }}

    /* ── Our custom classes ── */
    .bb-nav-label {{ font-size: {px(9)}; }}
    .bb-topbar-title {{ font-size: {px(13)}; }}
    .bb-topbar-subtitle {{ font-size: {px(9)}; }}
    .bb-topbar-right {{ font-size: {px(10)}; }}
    .bb-topbar-entity {{ font-size: {px(10)}; }}
    .bb-sidebar-logo-text {{ font-size: {px(11)}; }}
    .bb-sidebar-logo-sub {{ font-size: {px(8)}; }}
    .bb-sidebar-brand-mark {{ font-size: {px(10)}; }}
    .bb-brand-mark {{ font-size: {px(11)}; }}
    .bb-section-title {{ font-size: {px(10)}; }}
    .bb-section-sub {{ font-size: {px(10)}; }}
    .bb-metric-label {{ font-size: {px(8)}; }}
    .bb-metric-value {{ font-size: {px(18)}; }}
    .bb-metric-period {{ font-size: {px(8)}; }}
    .bb-agent-title {{ font-size: {px(9)}; }}
    .bb-metric-row {{ font-size: {px(11)}; }}
    .bb-mkey, .bb-mval {{ font-size: {px(11)}; }}
    .bb-analysis {{ font-size: {px(11)}; }}
    .bb-body-text {{ font-size: {px(11)}; }}
    .bb-pillar-badge {{ font-size: {px(9)}; }}
    .bb-skip-card {{ font-size: {px(11)}; }}
    .bb-legend-item {{ font-size: {px(10)}; }}
    </style>"""
    st.markdown(font_css, unsafe_allow_html=True)

    if light_mode:
        light_css = """
        <style>
        /* ── Light mode token overrides ── */
        :root {
            --c-bg:      #FFFFFF;
            --c-bg2:     #F7F8FA;
            --c-bg3:     #EDEEF2;
            --c-border:  #DFE1E8;
            --c-border2: #CDD0DA;
            --c-text:    #141520;
            --c-text2:   #3D3F52;
            --c-text3:   #7A7D96;
            --c-accent:  #B87C24;
            --c-cyan:    #1B7A96;
            --c-green:   #237A50;
            --c-red:     #A03020;
        }

        /* ── App shell ── */
        .stApp {
            background-color: #FFFFFF !important;
            color: #141520 !important;
        }

        /* ── Sidebar ── */
        [data-testid="stSidebar"],
        [data-testid="stSidebar"] > div,
        [data-testid="stSidebar"] > div > div,
        [data-testid="stSidebarContent"],
        section[data-testid="stSidebar"] > div:first-child {
            background-color: #EDEEF2 !important;
            background: #EDEEF2 !important;
        }
        /* All text inside sidebar */
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] div,
        [data-testid="stSidebar"] .stMarkdown p {
            color: #3D3F52 !important;
        }
        [data-testid="stSidebar"] .stRadio label { color: #3D3F52 !important; }
        [data-testid="stSidebar"] .stRadio label:hover { color: #B87C24 !important; }
        /* Radio button circles */
        [data-testid="stSidebar"] [data-baseweb="radio"] [role="radio"] div {
            border-color: #CDD0DA !important;
        }
        [data-testid="stSidebar"] [data-baseweb="radio"] [aria-checked="true"] div {
            background: #B87C24 !important;
            border-color: #B87C24 !important;
        }
        [data-testid="stSidebar"] .stTextInput input {
            background: #FFFFFF !important;
            border-color: #CDD0DA !important;
            color: #141520 !important;
        }
        [data-testid="stSidebar"] .stTextInput input:focus {
            border-color: #B87C24 !important;
        }
        [data-testid="stSidebar"] .stSlider [data-baseweb="slider"] { background: #DFE1E8 !important; }
        .bb-sidebar-logo { border-bottom-color: #DFE1E8 !important; }
        .bb-sidebar-brand-mark { background: #B87C24 !important; color: #FFFFFF !important; }
        .bb-sidebar-logo-text { color: #B87C24 !important; }
        .bb-sidebar-logo-sub, .bb-nav-label { color: #7A7D96 !important; }
        .bb-hr { border-top-color: #DFE1E8 !important; }

        /* ── Top bar ── */
        .bb-topbar {
            background: #F7F8FA !important;
            border-bottom-color: #B87C24 !important;
        }
        .bb-topbar-title { color: #B87C24 !important; }
        .bb-topbar-subtitle, .bb-topbar-right { color: #7A7D96 !important; }
        .bb-topbar-entity { color: #B87C24 !important; }
        .bb-brand-mark { background: #B87C24 !important; color: #FFFFFF !important; }

        /* ── Text inputs / selects in main area ── */
        .stTextInput input, .stTextArea textarea, .stSelectbox select {
            background: #FFFFFF !important;
            color: #141520 !important;
            border-color: #CDD0DA !important;
        }
        .stSelectbox [data-baseweb="select"] {
            background: #FFFFFF !important;
        }
        .stSelectbox [data-baseweb="select"] > div {
            background: #FFFFFF !important;
            color: #141520 !important;
            border-color: #CDD0DA !important;
        }

        /* ── Tabs ── */
        [data-testid="stTabs"] [role="tablist"] {
            border-bottom-color: #DFE1E8 !important;
            background: transparent !important;
        }
        [data-testid="stTabs"] [role="tab"] { color: #7A7D96 !important; }
        [data-testid="stTabs"] [role="tab"]:hover { color: #B87C24 !important; }
        [data-testid="stTabs"] [aria-selected="true"] {
            color: #B87C24 !important;
            border-bottom-color: #B87C24 !important;
        }
        [data-testid="stTabs"] [role="tab"] p { color: inherit !important; }

        /* ── Expanders ── */
        [data-testid="stExpander"] {
            background: #FFFFFF !important;
            border-color: #DFE1E8 !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
        }
        [data-testid="stExpander"] summary {
            background: #F7F8FA !important;
            color: #3D3F52 !important;
        }
        [data-testid="stExpander"] summary > p { color: #3D3F52 !important; }
        [data-testid="stExpander"] summary:hover,
        [data-testid="stExpander"] summary:hover > p { color: #B87C24 !important; }
        [data-testid="stExpander"] summary > span:first-child { color: #7A7D96 !important; }

        /* ── File uploader ── */
        [data-testid="stFileUploaderDropzone"],
        [data-testid="stFileUploadDropzone"] {
            background-color: #F7F8FA !important;
            border-color: #CDD0DA !important;
        }
        [data-testid="stFileUploaderDropzone"]:hover,
        [data-testid="stFileUploadDropzone"]:hover { border-color: #B87C24 !important; }
        [data-testid="stFileUploaderDropzone"] small,
        [data-testid="stFileUploadDropzone"] small { color: #7A7D96 !important; }
        [data-testid="stFileUploaderDropzone"] button,
        [data-testid="stFileUploadDropzone"] button {
            background: #FFFFFF !important;
            border-color: #CDD0DA !important;
            color: #3D3F52 !important;
        }

        /* ── Buttons (regular + download) ── */
        .stButton > button,
        .stDownloadButton > button,
        [data-testid="stDownloadButton"] > button {
            background: transparent !important;
            color: #B87C24 !important;
            border: 1px solid #B87C24 !important;
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover,
        [data-testid="stDownloadButton"] > button:hover {
            background: #B87C24 !important;
            color: #FFFFFF !important;
        }
        /* Also fix any remaining Streamlit default black fill */
        button[kind="secondary"],
        button[kind="primary"] {
            background: transparent !important;
        }

        /* ── DataFrames ── */
        [data-testid="stDataFrame"] { border-color: #DFE1E8 !important; }
        [data-testid="stDataFrame"] th {
            background: #F7F8FA !important;
            color: #B87C24 !important;
        }
        [data-testid="stDataFrame"] td {
            background: #FFFFFF !important;
            color: #141520 !important;
            border-color: #DFE1E8 !important;
        }

        /* ── Alerts ── */
        [data-testid="stAlert"] { background: #F7F8FA !important; color: #141520 !important; }
        div[data-baseweb="notification"] { background: #F7F8FA !important; }

        /* ── Sliders ── */
        [data-testid="stSlider"] label { color: #7A7D96 !important; }

        /* ── Custom components ── */
        .bb-section { border-bottom-color: #DFE1E8 !important; }
        .bb-section-title { color: #B87C24 !important; }
        .bb-section-sub { color: #7A7D96 !important; }

        .bb-metric-card {
            background: #FFFFFF !important;
            border-color: #DFE1E8 !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
        }
        .bb-metric-label { color: #7A7D96 !important; }
        .bb-metric-value { color: #B87C24 !important; }
        .bb-metric-card.cyan  .bb-metric-value { color: #1B7A96 !important; }
        .bb-metric-card.green .bb-metric-value { color: #237A50 !important; }
        .bb-metric-card.red   .bb-metric-value { color: #A03020 !important; }
        .bb-metric-period { color: #7A7D96 !important; }

        .bb-agent-card {
            background: #FFFFFF !important;
            border-color: #DFE1E8 !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
        }
        .bb-agent-title { color: #B87C24 !important; border-bottom-color: #DFE1E8 !important; }
        .bb-agent-card.liq  .bb-agent-title { color: #1B7A96 !important; }
        .bb-agent-card.bs   .bb-agent-title { color: #A03020 !important; }
        .bb-agent-card.xref .bb-agent-title { color: #237A50 !important; }
        .bb-metric-row { border-bottom-color: #F0F1F4 !important; }
        .bb-mkey { color: #7A7D96 !important; }
        .bb-mval { color: #141520 !important; }
        .bb-analysis { color: #3D3F52 !important; border-top-color: #DFE1E8 !important; }

        .bb-skip-card {
            background: #FFF5F4 !important;
            border-color: #E8C0BC !important;
            color: #8B3020 !important;
        }
        .bb-basel-panel {
            background: #FFFFFF !important;
            border-color: #DFE1E8 !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
        }
        .bb-body-text { color: #3D3F52 !important; }

        /* ── Scrollbar in light mode ── */
        ::-webkit-scrollbar-track { background: #F7F8FA; }
        ::-webkit-scrollbar-thumb { background: #CDD0DA; }
        ::-webkit-scrollbar-thumb:hover { background: #B87C24; }

        /* ── Main content text ── */
        .stMarkdown, .stMarkdown p, .stMarkdown li,
        .stMarkdown span, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3,
        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stText"], [data-testid="stCaption"],
        [data-testid="stAlert"] p,
        .element-container p, .element-container span,
        .stApp p, .stApp li, .stApp span:not([class*="material"]) {
            color: #141520 !important;
        }
        /* Inputs and selects in main area */
        .stTextInput input, .stTextArea textarea {
            background: #FFFFFF !important;
            color: #141520 !important;
            border-color: #CDD0DA !important;
        }
        .stSelectbox [data-baseweb="select"] > div {
            background: #FFFFFF !important;
            color: #141520 !important;
            border-color: #CDD0DA !important;
        }
        /* Number inputs */
        .stNumberInput input { background: #FFFFFF !important; color: #141520 !important; }
        /* Caption / helper text */
        .stCaption, [data-testid="stCaptionContainer"] { color: #7A7D96 !important; }
        </style>
        """
        st.markdown(light_css, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Top bar
# ─────────────────────────────────────────────────────────────────────────────

def render_top_bar(entity: str = "—") -> None:
    """Render the FinVeritas top bar."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d  %H:%M:%S UTC")
    entity_display = html.escape(entity.upper() if entity != "—" else "—")
    st.markdown(
        f"""
        <div class="bb-topbar">
            <div class="bb-topbar-brand">
                <div class="bb-brand-mark">FV</div>
                <div>
                    <div class="bb-topbar-title">FinVeritas</div>
                    <div class="bb-topbar-subtitle">Explainable Financial Analysis Platform</div>
                </div>
            </div>
            <div class="bb-topbar-right">
                <span><span class="bb-status-dot"></span>ONLINE</span>
                <span>ENTITY: <span class="bb-topbar-entity">{entity_display}</span></span>
                <span>{now}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Section header
# ─────────────────────────────────────────────────────────────────────────────

def render_section_header(title: str, subtitle: str = "") -> None:
    sub_html = (
        f'<div class="bb-section-sub">{html.escape(subtitle)}</div>'
        if subtitle else ""
    )
    st.markdown(
        f'<div class="bb-section">'
        f'<div class="bb-section-title">{html.escape(title)}</div>'
        f'{sub_html}</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Metric cards
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_value(v: float | None) -> str:
    """Format a numeric value for display."""
    if v is None:
        return "N/A"
    av = abs(v)
    if av >= 1_000_000:
        return f"{v / 1_000_000:,.2f}M"
    if av >= 1_000:
        return f"{v / 1_000:,.1f}K"
    return f"{v:,.2f}"


def _latest(ts: dict[str, Any], field: str) -> tuple[str, str]:
    """Return (formatted_value, period) for the most recent non-null entry."""
    series = ts.get(field) or []
    for item in reversed(series):
        if isinstance(item, dict) and item.get("value") is not None:
            return _fmt_value(float(item["value"])), str(item.get("period", "—"))
    return "N/A", "—"


def render_metric_cards(payload: dict[str, Any]) -> None:
    """Render four key metric cards from the OCR payload."""
    ts = payload.get("time_series") or {}

    cards = [
        ("revenue",           "REVENUE",           ""),
        ("total_assets",      "TOTAL ASSETS",       "cyan"),
        ("total_liabilities", "TOTAL LIABILITIES",  "red"),
        ("equity",            "EQUITY",             "green"),
    ]

    # Use native columns to avoid Markdown code-block detection on indented HTML
    cols = st.columns(4)
    for col, (field, label, cls) in zip(cols, cards):
        value, period = _latest(ts, field)
        col.markdown(
            f'<div class="bb-metric-card {cls}">'
            f'<div class="bb-metric-label">{label}</div>'
            f'<div class="bb-metric-value">{html.escape(value)}</div>'
            f'<div class="bb-metric-period">{html.escape(period)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Agent cards
# ─────────────────────────────────────────────────────────────────────────────

def _flat_metrics_rows(metrics: dict[str, Any]) -> str:
    """Render a flat metrics dict as table rows HTML."""
    rows = []
    for k, v in metrics.items():
        key_label = k.replace("_", " ").upper()
        if isinstance(v, float):
            val_str = f"{v:.4f}" if abs(v) < 100 else f"{v:,.2f}"
        elif isinstance(v, dict):
            continue  # skip nested (handled separately)
        else:
            val_str = str(v)
        rows.append(
            f'<div class="bb-metric-row">'
            f'<span class="bb-mkey">{html.escape(key_label)}</span>'
            f'<span class="bb-mval">{html.escape(val_str)}</span>'
            f"</div>"
        )
    return "".join(rows)


def render_agent_card(
    title: str,
    output: dict[str, Any],
    css_variant: str = "",   # "", "liq", "bs", "xref"
    icon: str = "◆",
) -> None:
    """Render a Bloomberg-style terminal card for a single agent result."""
    card_class = f"bb-agent-card {css_variant}".strip()

    # ── Error / skip ──────────────────────────────────────────
    if isinstance(output.get("error"), str):
        msg = html.escape(output["error"])
        st.markdown(
            f'<div class="bb-skip-card"><strong>⚠ {html.escape(title).upper()}</strong>'
            f" — {msg}</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Success ───────────────────────────────────────────────
    metrics = output.get("metrics") or {}
    analysis = output.get("analysis") or ""

    # For cross-reference the metrics dict is nested; skip flat rendering.
    if metrics and not any(isinstance(v, dict) for v in metrics.values()):
        metric_rows_html = _flat_metrics_rows(metrics)
    else:
        metric_rows_html = ""

    # Render card frame + metrics (keep single-line to avoid Markdown code-block detection)
    st.markdown(
        f'<div class="{card_class}"><div class="bb-agent-title">{icon} {html.escape(title)}</div>{metric_rows_html}</div>',
        unsafe_allow_html=True,
    )

    # Render analysis separately — replace newlines with <br> so blank lines
    # inside LLM output don't break the Markdown HTML block parser
    if analysis:
        escaped = html.escape(analysis).replace("\n", "<br>")
        st.markdown(
            f'<div class="bb-analysis">{escaped}</div>',
            unsafe_allow_html=True,
        )


def render_cross_ref_card(output: dict[str, Any]) -> None:
    """Dedicated renderer for the Cross Reference Agent (nested metrics, long analysis)."""
    if isinstance(output.get("error"), str):
        msg = html.escape(output["error"])
        st.markdown(
            f'<div class="bb-skip-card"><strong>⚠ CROSS REFERENCE AGENT</strong> — {msg}</div>',
            unsafe_allow_html=True,
        )
        return

    analysis = output.get("analysis") or ""
    nested = output.get("metrics") or {}

    # Summarise each sub-agent's key metric
    summary_rows = ""
    colours = {
        "revenue": "#FFB000",
        "liquidity": "#00BFFF",
        "balance_sheet": "#FF6B35",
        "sentiment": "#CC88FF",
    }
    for key, colour in colours.items():
        sub = nested.get(key) or {}
        if not sub:
            continue
        # Pick the most representative metric
        representative = {
            "revenue":       ("cagr", "CAGR"),
            "liquidity":     ("liquidity_risk_flag", "LIQUIDITY RISK"),
            "balance_sheet": ("balance_sheet_risk",  "BS RISK"),
            "sentiment":     ("dominant_sentiment",  "PUBLIC SENTIMENT"),
        }.get(key, (None, ""))
        field, label = representative
        val = sub.get(field, "—") if field else "—"
        if isinstance(val, float):
            val_str = f"{val:.2f}"
        else:
            val_str = str(val)
        summary_rows += (
            f'<div class="bb-metric-row">'
            f'<span class="bb-mkey" style="color:{colour};">{key.replace("_"," ").upper()} — {label}</span>'
            f'<span class="bb-mval">{html.escape(val_str)}</span>'
            f"</div>"
        )

    # Render card frame + summary rows
    st.markdown(
        f'<div class="bb-agent-card xref"><div class="bb-agent-title">◈ CROSS REFERENCE AGENT — INTEGRATED ANALYSIS</div>{summary_rows}</div>',
        unsafe_allow_html=True,
    )

    # Render analysis separately — replace newlines with <br> so blank lines
    # inside LLM output don't break the Markdown HTML block parser
    if analysis:
        escaped = html.escape(analysis).replace("\n", "<br>")
        st.markdown(
            f'<div class="bb-analysis">{escaped}</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Workflow graph tooltip helpers
# ─────────────────────────────────────────────────────────────────────────────

def agent_tooltip_html(name: str, output: dict[str, Any] | None) -> str:
    """Build an HTML tooltip string for use as a vis.js node title."""
    if not output:
        return f"<b>{name}</b><br><i>Not yet run</i>"

    if isinstance(output.get("error"), str):
        err = output["error"][:120]
        return f"<b>{name}</b><br><span style='color:#FF7777'>⚠ {err}</span>"

    metrics = output.get("metrics") or {}
    lines = [f"<b style='color:#FFB000'>{name}</b>", ""]

    for k, v in metrics.items():
        if isinstance(v, dict):
            continue
        if isinstance(v, float):
            val_str = f"{v:.3f}" if abs(v) < 100 else f"{v:,.0f}"
        else:
            val_str = str(v)
        label = k.replace("_", " ").upper()
        lines.append(f"<b>{label}:</b> {val_str}")

    analysis = output.get("analysis")
    if isinstance(analysis, str) and analysis:
        # First 160 chars of the analysis
        snippet = analysis[:160] + ("…" if len(analysis) > 160 else "")
        lines += ["", f"<i style='color:#AAAAAA'>{snippet}</i>"]

    return "<br>".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Divider
# ─────────────────────────────────────────────────────────────────────────────

def render_hr() -> None:
    st.markdown('<div class="bb-hr"></div>', unsafe_allow_html=True)
