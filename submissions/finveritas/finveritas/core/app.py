"""Bloomberg Terminal-style Explainable Financial Analysis System.

Pages
-----
1. Upload Financial Statement  — 3 tabs: Bloomberg PDF / Fetch by Ticker / Private Company CSV
2. Agent Workflow              — interactive pipeline diagram with hover tooltips
3. Financial Analysis          — full agent output cards
4. Basel III Alignment         — regulatory context panel
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph

from agents import (
    balance_sheet_agent,
    cross_reference_agent,
    liquidity_agent,
    revenue_agent,
    sentiment_agent,
)
from ocr.pdf_parser import parse_pdf_to_json, payload_to_agent_files
from src.yfinance_ingestion import fetch_by_ticker
from src.private_company_ingestion import load_private_company_data, get_template_csv
from src.supplemental_fetchers import auto_fetch_missing_fields
from src.data_verifier import run_verification, CredibilityReport, STATUS_PASS, STATUS_WARN, STATUS_FAIL, STATUS_SKIP
from src.audit_log import append_entry as audit_append, read_log as audit_read_log, verify_chain as audit_verify_chain
from src.aa_ingestion import parse_aa_deposit, sample_json as aa_sample_json
from src import db as _db
from src import meta_agent as _meta
from ui.dashboard_components import (
    agent_tooltip_html,
    inject_theme_vars,
    load_css,
    render_agent_card,
    render_cross_ref_card,
    render_hr,
    render_metric_cards,
    render_section_header,
    render_top_bar,
)

_DEFAULT_BASE_URL     = "http://127.0.0.1:1234/v1"
_DEFAULT_MODEL        = "qwen2.5-coder-1.5b-instruct-mlx"
_DEFAULT_API_KEY      = "local"
_DEFAULT_NEWS_API_KEY = ""
_DEFAULT_FMP_KEY      = ""
_DEFAULT_AV_KEY       = ""


def _env_default_api_key(provider: str) -> str:
    """Pick a provider-aware default API key from environment variables."""
    p = (provider or "").strip().lower()
    llm = os.environ.get("LLM_API_KEY", "")
    gem = os.environ.get("GEMINI_API_KEY", "")
    grq = os.environ.get("GROQ_API_KEY", "")

    if p == "groq":
        return grq or llm or _DEFAULT_API_KEY
    if p == "gemini":
        return gem or llm or _DEFAULT_API_KEY
    return llm or gem or grq or _DEFAULT_API_KEY


def _load_dotenv_fallback() -> None:
    """Minimal .env loader (no external dependency).

    Loads key=value lines into process environment only when the key is not
    already present in os.environ.
    """
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[3] / ".env",  # workspace root
        Path(__file__).resolve().parents[2] / ".env",  # repo root fallback
    ]
    seen: set[Path] = set()
    for env_path in candidates:
        env_path = env_path.resolve()
        if env_path in seen or not env_path.exists() or not env_path.is_file():
            continue
        seen.add(env_path)
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv_fallback()

_DEFAULT_PROVIDER     = os.environ.get("LLM_PROVIDER", "Local / OpenAI-compatible")
_DEFAULT_BASE_URL     = os.environ.get("LLM_BASE_URL", _DEFAULT_BASE_URL)
_DEFAULT_MODEL        = os.environ.get("LLM_MODEL", _DEFAULT_MODEL)
_DEFAULT_API_KEY      = _env_default_api_key(_DEFAULT_PROVIDER)
_DEFAULT_NEWS_API_KEY = os.environ.get("NEWS_API_KEY", _DEFAULT_NEWS_API_KEY)
_DEFAULT_FMP_KEY      = os.environ.get("FMP_API_KEY", _DEFAULT_FMP_KEY)
_DEFAULT_AV_KEY       = os.environ.get("ALPHA_VANTAGE_API_KEY", _DEFAULT_AV_KEY)


def _llm_config_error(base_url: str, api_key: str) -> str | None:
    """Return a user-facing config error string if LLM credentials look invalid."""
    b = (base_url or "").strip().lower()
    k = (api_key or "").strip()

    if not k or k.lower() in {"local", "api key", "google ai studio key", "groq api key"}:
        return "Missing/placeholder LLM API key in sidebar."

    if "generativelanguage.googleapis.com" in b and not k.startswith("AIza"):
        return "Gemini endpoint selected, but API key does not look like a Gemini key (expected prefix: AIza)."

    if "api.groq.com" in b and not k.startswith("gsk_"):
        return "Groq endpoint selected, but API key does not look like a Groq key (expected prefix: gsk_)."

    if k.lower() == "not-needed":
        return None  # vLLM ROCm runs locally — no key required

    return None


def _provider_defaults(provider: str) -> tuple[str, str, str]:
    """Return (base_url, model, api_key_placeholder) for a selected LLM provider."""
    provider = (provider or "").strip().lower()
    if provider == "gemini":
        return (
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            "gemini-2.0-flash",
            "Google AI Studio key",
        )
    if provider == "groq":
        return (
            "https://api.groq.com/openai/v1",
            "llama-3.3-70b-versatile",
            "Groq API key",
        )
    if provider == "vllm-rocm":
        return (
            "http://localhost:8000/v1",
            "Qwen/Qwen2.5-7B-Instruct",
            "not-needed",
        )
    if provider == "openai-compatible":
        return (
            _DEFAULT_BASE_URL,
            _DEFAULT_MODEL,
            "API key",
        )
    return (
        _DEFAULT_BASE_URL,
        _DEFAULT_MODEL,
        "local",
    )


def _safe_run(name: str, fn) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        return {"error": f"{name} failed: {exc}", "traceback": traceback.format_exc()}


def _preview_df(payload: dict[str, Any]) -> pd.DataFrame:
    ts = payload.get("time_series") or {}
    fields = ["revenue", "total_assets", "total_liabilities", "equity"]
    rows = []
    for field in fields:
        for item in ts.get(field) or []:
            if isinstance(item, dict) and item.get("value") is not None:
                rows.append({"field": field, "period": item.get("period"), "value": item.get("value")})
    if not rows:
        return pd.DataFrame(columns=["field", "period", "value"])
    df = pd.DataFrame(rows).dropna(subset=["period", "value"])
    df["period"] = df["period"].astype(str)
    df = df.sort_values(["field", "period"]).groupby("field", as_index=False).tail(5)
    return df[["field", "period", "value"]]


def _available_fields(payload: dict[str, Any]) -> set[str]:
    ts = payload.get("time_series") or {}
    return {k for k, v in ts.items() if isinstance(v, list) and len(v) > 0}


def _render_credibility_panel(
    report: CredibilityReport,
) -> None:
    """Render the Data Credibility Score card."""
    score = report.score
    confidence = report.confidence
    colour = report.confidence_colour

    conf_label = {"HIGH": "HIGH CONFIDENCE", "MEDIUM": "MEDIUM CONFIDENCE", "LOW": "LOW CONFIDENCE"}
    check_label = {
        STATUS_PASS: ("PASS", "#3AB87A"),
        STATUS_WARN: ("WARN", "#D4963A"),
        STATUS_FAIL: ("FAIL", "#C94A3A"),
        STATUS_SKIP: ("SKIP", "#5A5A72"),
    }

    # Score card
    st.markdown(
        f'<div style="background:var(--c-bg2,#10121A);border:1px solid {colour}22;'
        f'border-left:3px solid {colour};border-radius:2px;padding:12px 16px;margin:6px 0;">'
        f'<div style="display:flex;align-items:center;gap:20px;">'
        f'<div style="font-size:36px;font-weight:700;color:{colour};font-family:monospace;line-height:1;">{score}</div>'
        f'<div>'
        f'<div style="font-size:8px;color:var(--c-text3,#5A5A72);letter-spacing:0.18em;text-transform:uppercase;margin-bottom:3px;">CREDIBILITY SCORE / 100</div>'
        f'<div style="font-size:12px;color:{colour};font-weight:700;letter-spacing:0.12em;">{conf_label[confidence]}</div>'
        f'<div style="font-size:9px;color:var(--c-text3,#5A5A72);margin-top:3px;letter-spacing:0.06em;">'
        f'SOURCE: {report.source.replace("_"," ").upper()} &nbsp;&middot;&nbsp; ENTITY: {report.entity}'
        f'</div></div></div></div>',
        unsafe_allow_html=True,
    )

    with st.expander("View detailed credibility checks", expanded=False):
        for check in report.checks:
            badge_text, badge_col = check_label.get(check.status, ("SKIP", "#5A5A72"))
            st.markdown(
                f'<div style="display:flex;gap:10px;align-items:flex-start;padding:6px 0;border-bottom:1px solid var(--c-border,#1E2030);">'
                f'<span style="font-size:9px;font-weight:700;color:{badge_col};background:{badge_col}18;'
                f'padding:1px 5px;border-radius:2px;letter-spacing:0.1em;margin-top:1px;white-space:nowrap;">{badge_text}</span>'
                f'<div>'
                f'<span style="font-size:11px;color:var(--c-text,#D8D8E0);font-weight:600;">{check.name}</span><br>'
                f'<span style="font-size:10px;color:var(--c-text3,#5A5A72);font-family:monospace;">{check.detail}</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            '<p style="font-size:9px;color:var(--c-text3,#5A5A72);margin-top:6px;">'
            'Score = weighted average of non-skipped checks.</p>',
            unsafe_allow_html=True,
        )


def _get_periods_from_payload(payload: dict[str, Any]) -> list[str]:
    """Extract all unique periods present in any time_series field, sorted."""
    import re
    ts = payload.get("time_series") or {}
    periods: set[str] = set()
    for entries in ts.values():
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and e.get("period"):
                    periods.add(str(e["period"]))
    def _sort_key(p: str):
        m = re.match(r"^(\d{4})-(FY|Q[1-4])$", p)
        if not m:
            return (0, 0)
        year = int(m.group(1))
        tag  = m.group(2)
        return (year, 5 if tag == "FY" else int(tag[1:]))
    return sorted(periods, key=_sort_key)


def _patch_payload_field(
    payload: dict[str, Any],
    field: str,
    period_values: dict[str, float],
) -> dict[str, Any]:
    """Add/overwrite a time_series field with user-supplied period→value pairs."""
    import copy
    p = copy.deepcopy(payload)
    ts = p.setdefault("time_series", {})
    existing = {e["period"]: e["value"] for e in ts.get(field, []) if isinstance(e, dict)}
    existing.update(period_values)
    ts[field] = sorted(
        [{"period": k, "value": v} for k, v in existing.items()],
        key=lambda x: x["period"],
    )
    return p


def _render_missing_data_supplement(
    payload: dict[str, Any],
    agent_paths: dict,
    written_path: Any,
    source_label: str,
    fmp_api_key: str = "",
    av_api_key: str = "",
) -> tuple[dict[str, Any], dict, Any]:
    """Show an expander with auto-fetch + manual entry for missing fields."""
    avail = _available_fields(payload)

    _LIQUIDITY_REQUIRED = {"current_assets", "current_liabilities", "total_assets", "total_liabilities", "equity"}
    _BS_REQUIRED        = {"total_assets", "total_liabilities", "equity"}

    missing_liq = sorted(_LIQUIDITY_REQUIRED - avail)
    missing_bs  = sorted(_BS_REQUIRED - avail)
    all_missing = sorted(set(missing_liq) | set(missing_bs))

    if not all_missing:
        return payload, agent_paths, written_path

    periods = _get_periods_from_payload(payload)
    if not periods:
        return payload, agent_paths, written_path

    # Pre-filled values from auto-fetch (stored in session_state)
    prefilled: dict[str, dict[str, float]] = st.session_state.get("supp_prefilled", {})

    # Detect ticker for auto-fetch (only relevant for ticker source)
    cached_src = st.session_state.get("ocr_cache", {}).get("cache_key", (None,))
    ticker_for_fetch: str | None = None
    if isinstance(cached_src, tuple) and len(cached_src) >= 2 and cached_src[0] == "ticker":
        ticker_for_fetch = cached_src[1]

    with st.expander(
        f"⚠️  Insufficient Data — {len(all_missing)} field(s) missing: "
        f"{', '.join(all_missing)}",
        expanded=True,
    ):
        st.markdown(
            '<p style="font-size:11px;color:#aaa;font-family:monospace;">'
            f"Missing: <b>{', '.join(all_missing)}</b>. "
            "These fields are required by the Liquidity / Balance Sheet agents. "
            "Auto-fetch from a financial data API, or enter values manually below.</p>",
            unsafe_allow_html=True,
        )

        # ── Section A: Auto-fetch buttons ────────────────────────────────────
        if ticker_for_fetch:
            st.markdown("**Step 1 — Auto-fetch missing data** *(requires API key in sidebar)*")
            col_fmp, col_av, col_status = st.columns([1, 1, 2])

            has_fmp = bool(fmp_api_key and fmp_api_key.strip())
            has_av  = bool(av_api_key  and av_api_key.strip())

            if col_fmp.button(
                "Fetch via FMP",
                key="autofetch_fmp_btn",
                disabled=not has_fmp,
                help="Add FMP API key in sidebar first (financialmodelingprep.com)" if not has_fmp else "Fetch from Financial Modeling Prep",
            ):
                with st.spinner("Fetching from FMP…"):
                    resolved, resolved_fields, errors = auto_fetch_missing_fields(
                        ticker=ticker_for_fetch,
                        missing_fields=set(all_missing),
                        fmp_api_key=fmp_api_key,
                        av_api_key=None,
                    )
                if resolved_fields:
                    st.session_state["supp_prefilled"] = {
                        field: {e["period"]: e["value"] for e in series}
                        for field, series in resolved.items()
                    }
                    prefilled = st.session_state["supp_prefilled"]
                    st.success(f"FMP resolved: {', '.join(resolved_fields)}")
                for err in errors:
                    st.warning(f"{err}")
                if not resolved_fields:
                    st.error("FMP could not resolve any missing fields. Try Alpha Vantage or enter manually.")

            if col_av.button(
                "Fetch via Alpha Vantage",
                key="autofetch_av_btn",
                disabled=not has_av,
                help="Add AV API key in sidebar first (alphavantage.co)" if not has_av else "Fetch from Alpha Vantage",
            ):
                with st.spinner("Fetching from Alpha Vantage…"):
                    resolved, resolved_fields, errors = auto_fetch_missing_fields(
                        ticker=ticker_for_fetch,
                        missing_fields=set(all_missing),
                        fmp_api_key=None,
                        av_api_key=av_api_key,
                    )
                if resolved_fields:
                    existing = st.session_state.get("supp_prefilled", {})
                    for field, series in resolved.items():
                        existing[field] = {e["period"]: e["value"] for e in series}
                    st.session_state["supp_prefilled"] = existing
                    prefilled = st.session_state["supp_prefilled"]
                    st.success(f"Alpha Vantage resolved: {', '.join(resolved_fields)}")
                for err in errors:
                    st.warning(f"{err}")
                if not resolved_fields:
                    st.error("Alpha Vantage could not resolve any missing fields. Enter manually below.")

            if not has_fmp and not has_av:
                col_status.markdown(
                    '<span style="font-size:10px;color:var(--c-text3,#5A5A72);">'
                    "Add FMP or Alpha Vantage key in the sidebar to enable auto-fetch."
                    "</span>",
                    unsafe_allow_html=True,
                )

            st.markdown("---")

        # Section B: Manual entry
        st.markdown("**Step 2 — Review / enter values manually**")
        st.markdown(
            '<p style="font-size:10px;color:var(--c-text3,#5A5A72);font-family:monospace;">'
            "Auto-fetched values are pre-filled below. Edit or complete any blanks. "
            "Use the same unit as your other figures (e.g. millions).</p>",
            unsafe_allow_html=True,
        )

        input_values: dict[str, dict[str, str]] = {f: {} for f in all_missing}

        header_cols = st.columns([1] + [1] * len(all_missing))
        header_cols[0].markdown("**Period**")
        for i, field in enumerate(all_missing):
            header_cols[i + 1].markdown(f"**{field}**")

        for period in periods:
            row_cols = st.columns([1] + [1] * len(all_missing))
            row_cols[0].markdown(
                f'<span style="font-size:11px;color:#FFB000;font-family:monospace;">{period}</span>',
                unsafe_allow_html=True,
            )
            for i, field in enumerate(all_missing):
                # Pre-populate with auto-fetched value if available
                pre_val = prefilled.get(field, {}).get(period)
                default  = str(int(pre_val)) if pre_val is not None else ""
                val = row_cols[i + 1].text_input(
                    label=f"{field}_{period}",
                    label_visibility="collapsed",
                    placeholder="e.g. 150000",
                    value=default,
                    key=f"supp_{field}_{period}",
                )
                input_values[field][period] = val

        # ── Section C: Apply button ───────────────────────────────────────────
        if st.button("Apply Supplemental Data", key="apply_supplement_btn"):
            patched = payload
            applied_any = False
            errors_apply: list[str] = []

            for field, period_map in input_values.items():
                parsed: dict[str, float] = {}
                for period, raw in period_map.items():
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        parsed[period] = float(raw.replace(",", ""))
                        applied_any = True
                    except ValueError:
                        errors_apply.append(f"{field} / {period}: '{raw}' is not a number")
                if parsed:
                    patched = _patch_payload_field(patched, field, parsed)

            for err in errors_apply:
                st.warning(f"⚠ {err}")

            if applied_any and not errors_apply:
                _, new_written, new_agent_paths = payload_to_agent_files(patched, output_dir="output")
                c = st.session_state.get("ocr_cache", {})
                c["payload"]      = patched
                c["agent_paths"]  = new_agent_paths
                c["written_path"] = new_written
                st.session_state["ocr_cache"] = c
                st.session_state.pop("agent_outputs", None)
                st.session_state.pop("supp_prefilled", None)   # clear prefill cache
                st.success(
                    f"✅ Supplemental data applied for: {', '.join(all_missing)}. "
                    "Now click ▶ RUN FULL ANALYSIS."
                )
                st.rerun()
            elif not applied_any:
                st.warning("No values were entered. Fill in at least one field.")

    current = st.session_state.get("ocr_cache", {})
    return (
        current.get("payload", payload),
        current.get("agent_paths", agent_paths),
        current.get("written_path", written_path),
    )


# ── DB agent logger ───────────────────────────────────────────────────────────

def _db_log_agent(run_id: str, name: str, output: dict, duration_ms: int) -> None:
    """Write one agent execution record to SQLite. Never raises."""
    try:
        err = output.get("error")
        if isinstance(err, str):
            status = "skipped" if "skipped" in err.lower() else "error"
            _db.log_agent(run_id=run_id, agent_name=name, status=status,
                          error_message=err, duration_ms=duration_ms)
        else:
            _db.log_agent(run_id=run_id, agent_name=name, status="success",
                          metrics=output.get("metrics"),
                          analysis_text=output.get("analysis"),
                          duration_ms=duration_ms)
    except Exception:
        pass


# ── Shared agent runner (used by all 3 ingestion tabs) ────────────────────────

def _run_agent_pipeline(
    payload: dict[str, Any],
    agent_paths: dict,
    base_url: str,
    model: str,
    api_key: str,
    news_api_key: str,
) -> None:
    """Run all 5 agents on pre-loaded data and store results in session_state."""
    avail       = _available_fields(payload)
    required_liq = {"current_assets", "current_liabilities", "total_assets", "total_liabilities", "equity"}
    required_bs  = {"total_assets", "total_liabilities", "equity"}
    missing_liq  = sorted(required_liq - avail)
    missing_bs   = sorted(required_bs  - avail)

    rev_path = agent_paths["revenue"]
    bs_path  = agent_paths["balance_sheet"]
    liq_path = agent_paths["liquidity"]
    entity   = str(payload.get("entity", {}).get("entity_id") or "UNKNOWN")

    # Generate a single run UUID shared by both SQLite and JSONL stores
    run_id = str(uuid.uuid4())
    input_hash = hashlib.sha256(
        json.dumps(payload.get("time_series", {}), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    try:
        _db.log_run(
            run_id=run_id,
            entity=entity,
            source_type=st.session_state.get("last_source_type", "unknown"),
            credibility_score=st.session_state.get("last_credibility_score"),
            input_hash=input_hash,
            consent_timestamp=st.session_state.get("consent_timestamp"),
        )
    except Exception:
        pass

    _t0 = time.monotonic()
    with st.spinner("Revenue Agent…"):
        rev_out = _safe_run("Revenue Agent",
            lambda: revenue_agent.run(json_path=rev_path, base_url=base_url, model=model, api_key=api_key, run_id=run_id))
    _db_log_agent(run_id, "revenue_agent", rev_out, int((time.monotonic() - _t0) * 1000))

    if missing_liq:
        liq_out: dict = {"error": f"Liquidity Agent skipped — missing: {', '.join(missing_liq)}"}
        _db_log_agent(run_id, "liquidity_agent", liq_out, 0)
    else:
        _t0 = time.monotonic()
        with st.spinner("Liquidity Agent…"):
            liq_out = _safe_run("Liquidity Agent",
                lambda: liquidity_agent.run(json_path=liq_path, base_url=base_url, model=model, api_key=api_key, run_id=run_id))
        _db_log_agent(run_id, "liquidity_agent", liq_out, int((time.monotonic() - _t0) * 1000))

    if missing_bs:
        bs_out: dict = {"error": f"Balance Sheet Agent skipped — missing: {', '.join(missing_bs)}"}
        _db_log_agent(run_id, "balance_sheet_agent", bs_out, 0)
    else:
        _t0 = time.monotonic()
        with st.spinner("Balance Sheet Agent…"):
            _bs_path = bs_path
            bs_out = _safe_run("Balance Sheet Agent",
                lambda: balance_sheet_agent.run(json_path=_bs_path, base_url=base_url, model=model, api_key=api_key, run_id=run_id))
        _db_log_agent(run_id, "balance_sheet_agent", bs_out, int((time.monotonic() - _t0) * 1000))

    _news_key = news_api_key.strip() if news_api_key else ""
    if not _news_key:
        sentiment_out: dict = {"error": "Sentiment Agent skipped — add a NewsAPI key in the sidebar (newsapi.org)."}
        _db_log_agent(run_id, "sentiment_agent", sentiment_out, 0)
    else:
        _t0 = time.monotonic()
        with st.spinner("Sentiment Agent…"):
            _ent = entity
            _nk  = _news_key
            sentiment_out = _safe_run(
                "Sentiment Agent",
                lambda: sentiment_agent.run(
                    company_name=_ent, news_api_key=_nk,
                    base_url=base_url, model=model, api_key=api_key, run_id=run_id,
                ),
            )
        _db_log_agent(run_id, "sentiment_agent", sentiment_out, int((time.monotonic() - _t0) * 1000))

    _sentiment_ok = sentiment_out and not isinstance(sentiment_out.get("error"), str)
    any_err = any(isinstance(x.get("error"), str) for x in [rev_out, liq_out, bs_out])
    if any_err:
        cross_out: dict = {"error": "Cross Reference Agent skipped — requires Revenue, Liquidity, and Balance Sheet agents to succeed."}
        _db_log_agent(run_id, "cross_reference_agent", cross_out, 0)
    else:
        _t0 = time.monotonic()
        with st.spinner("Cross Reference Agent…"):
            _rev, _liq, _bs = rev_out, liq_out, bs_out
            cross_out = _safe_run(
                "Cross Reference Agent",
                lambda: cross_reference_agent.run(
                    entity=entity, revenue=_rev, liquidity=_liq, balance_sheet=_bs,
                    sentiment=sentiment_out if _sentiment_ok else None,
                    base_url=base_url, model=model, api_key=api_key, run_id=run_id,
                ),
            )
        _db_log_agent(run_id, "cross_reference_agent", cross_out, int((time.monotonic() - _t0) * 1000))

    outputs = {
        "entity": entity, "revenue": rev_out, "liquidity": liq_out,
        "balance_sheet": bs_out, "sentiment": sentiment_out, "cross_reference": cross_out,
    }
    st.session_state["agent_outputs"] = outputs

    # ── Meta-Orchestrator: self-aware assessment over all agent outputs ────────
    with st.spinner("Meta-Orchestrator: self-assessment…"):
        _meta_out = _meta.run_meta_agent(
            entity=entity,
            outputs=outputs,
            run_id=run_id,
            base_url=base_url,
            model=model,
            api_key=api_key,
        )
    st.session_state["meta_assessment"] = _meta_out
    _db_log_agent(run_id, "meta_agent", {"metrics": _meta_out}, int((time.monotonic() - _t0) * 1000))

    # Determine which agents produced actual results (not error dicts)
    _agent_keys = [
        ("revenue_agent", "revenue"), ("liquidity_agent", "liquidity"),
        ("balance_sheet_agent", "balance_sheet"), ("sentiment_agent", "sentiment"),
        ("cross_reference_agent", "cross_reference"),
    ]
    _agents_run = [name for name, key in _agent_keys if not isinstance(outputs.get(key, {}).get("error"), str)]

    try:
        audit_append(
            run_id=run_id,
            entity=entity,
            source_type=st.session_state.get("last_source_type", "unknown"),
            credibility_score=st.session_state.get("last_credibility_score"),
            agents_run=_agents_run,
            agent_outputs=outputs,
            consent_timestamp=st.session_state.get("consent_timestamp"),
        )
    except Exception:
        pass  # audit failure must never block the analysis flow

    st.success("Analysis complete — navigate to **Financial Analysis** to view results.")


def _render_agent_status_badges(payload: dict[str, Any], news_api_key: str) -> None:
    avail       = _available_fields(payload)
    required_liq = {"current_assets", "current_liabilities", "total_assets", "total_liabilities", "equity"}
    required_bs  = {"total_assets", "total_liabilities", "equity"}
    missing_liq  = sorted(required_liq - avail)
    missing_bs   = sorted(required_bs  - avail)

    cols = st.columns(5)
    statuses = [
        ("REVENUE",       "revenue" in avail,                         "#FFB000"),
        ("LIQUIDITY",     not missing_liq,                             "#00BFFF"),
        ("BALANCE SHEET", not missing_bs,                              "#FF6B35"),
        ("SENTIMENT",     bool(news_api_key and news_api_key.strip()), "#CC88FF"),
        ("CROSS REF",     not missing_liq and not missing_bs,          "#00FF88"),
    ]
    for col, (name, ready, colour) in zip(cols, statuses):
        c = colour if ready else "#444"
        col.markdown(
            f'<div style="text-align:center;font-size:10px;color:{c};">{"●" if ready else "○"}&nbsp;{name}<br>'
            f'<span style="font-size:9px;color:#555;">{"READY" if ready else "MISSING DATA"}</span></div>',
            unsafe_allow_html=True,
        )


# ── Page 1 ────────────────────────────────────────────────────────────────────

def page_upload(base_url: str, model: str, api_key: str, news_api_key: str = "",
                fmp_api_key: str = "", av_api_key: str = "") -> None:
    render_section_header(
        "Financial Data Ingestion",
        subtitle="Choose your data source: Bloomberg PDF · Listed Ticker · Private Company CSV",
    )

    tab_pdf, tab_ticker, tab_csv, tab_aa = st.tabs([
        "Bloomberg PDF",
        "Fetch by Ticker",
        "Private Company (CSV / Excel)",
        "AA / RBI Consented Data",
    ])

    # ── Tab 1: Bloomberg PDF ──────────────────────────────────────────────────
    with tab_pdf:
        st.markdown(
            '<p style="font-size:11px;color:#666;font-family:monospace;">'
            "▸ Upload <b>both</b> the Income Statement PDF and the Balance Sheet PDF together "
            "to enable all agents. A single IS PDF enables the Revenue Agent only.</p>",
            unsafe_allow_html=True,
        )
        uploaded_files = st.file_uploader(
            "Drop Bloomberg PDF(s) here", type=["pdf"],
            accept_multiple_files=True, label_visibility="collapsed", key="pdf_uploader",
        )
        if not uploaded_files:
            st.markdown('<div style="color:#444;font-size:11px;margin-top:8px;">▸ Awaiting upload…</div>', unsafe_allow_html=True)
        else:
            cache_key = ("pdf",) + tuple(sorted(f.name for f in uploaded_files))
            cached = st.session_state.get("ocr_cache", {})
            if cached.get("cache_key") != cache_key:
                uploads = [(f.getvalue(), f.name) for f in uploaded_files]
                with st.spinner(f"Running OCR parser on {len(uploads)} file(s)…"):
                    try:
                        payload, written_path, agent_paths = parse_pdf_to_json(uploads=uploads, output_dir="output")
                    except Exception as exc:
                        st.error(f"OCR failed: {exc}")
                        st.stop()
                st.session_state["ocr_cache"] = {
                    "cache_key": cache_key, "payload": payload,
                    "written_path": written_path, "agent_paths": agent_paths,
                    "source_label": f"{len(uploads)} Bloomberg PDF(s)",
                }
                st.session_state.pop("agent_outputs", None)
                st.success(f"OCR complete — {len(uploads)} PDF(s) merged → `{written_path.name}`")
            else:
                st.info(f"Cached: `{cached['written_path'].name}`")

    # ── Tab 2: Fetch by Ticker (yfinance) ────────────────────────────────────
    with tab_ticker:
        st.markdown(
            '<p style="font-size:11px;color:#666;font-family:monospace;">'
            "▸ Enter a Yahoo Finance ticker to automatically fetch annual financial statements. "
            "Examples: <b>INFY.NS</b> (Infosys), <b>TCS.NS</b> (TCS), <b>AAPL</b> (Apple).</p>",
            unsafe_allow_html=True,
        )
        col_t1, col_t2 = st.columns([3, 1])
        ticker_input = col_t1.text_input(
            "Ticker Symbol", placeholder="e.g. INFY.NS, TCS.NS, AAPL",
            label_visibility="collapsed", key="ticker_input",
        )
        fetch_btn = col_t2.button("⬇  Fetch Data", use_container_width=True, key="fetch_ticker_btn")

        if fetch_btn and ticker_input.strip():
            ticker = ticker_input.strip().upper()
            cache_key = ("ticker", ticker)
            with st.spinner(f"Fetching financial data for {ticker} via yfinance…"):
                try:
                    payload = fetch_by_ticker(ticker)
                    _, written_path, agent_paths = payload_to_agent_files(payload, output_dir="output")
                except Exception as exc:
                    st.error(f"Ticker fetch failed: {exc}")
                    st.stop()
            st.session_state["ocr_cache"] = {
                "cache_key": cache_key, "payload": payload,
                "written_path": written_path, "agent_paths": agent_paths,
                "source_label": f"yfinance · {ticker}",
            }
            st.session_state.pop("agent_outputs", None)
            entity_name = payload.get("entity", {}).get("entity_id", ticker)
            st.success(f"Fetched: **{entity_name}** — {len(payload.get('time_series', {}))} fields available")
        elif fetch_btn:
            st.warning("Enter a ticker symbol first.")

        # Show cached ticker info
        cached = st.session_state.get("ocr_cache", {})
        if cached.get("cache_key", (None,))[0] == "ticker":
            st.info(f"Active dataset: {cached.get('source_label', '—')}")

    # ── Tab 3: Private Company CSV / Excel ───────────────────────────────────
    with tab_csv:
        st.markdown(
            '<p style="font-size:11px;color:#666;font-family:monospace;">'
            "▸ For private or non-listed companies: upload a CSV or Excel file with financial data. "
            "Columns: <b>period</b> (e.g. 2023-FY), revenue, total_assets, total_liabilities, "
            "current_assets, current_liabilities, equity, …</p>",
            unsafe_allow_html=True,
        )

        # Template download
        st.download_button(
            label="⬇  Download CSV Template",
            data=get_template_csv(),
            file_name="private_company_template.csv",
            mime="text/csv",
            key="csv_template_dl",
        )

        col_c1, col_c2 = st.columns([2, 1])
        company_name_input = col_c1.text_input(
            "Company Name", placeholder="e.g. Acme Pvt. Ltd.",
            label_visibility="visible", key="csv_company_name",
        )
        currency_input = col_c2.selectbox(
            "Currency", ["INR", "USD", "EUR", "GBP", "JPY", "SGD", "AED"],
            key="csv_currency",
        )
        csv_file = st.file_uploader(
            "Upload CSV or Excel file",
            type=["csv", "xlsx", "xls"],
            label_visibility="collapsed",
            key="csv_uploader",
        )

        if csv_file and st.button("⬆  Load Private Company Data", key="load_csv_btn"):
            if not company_name_input.strip():
                st.warning("Please enter the company name before loading.")
            else:
                cache_key = ("csv", csv_file.name, company_name_input.strip())
                with st.spinner("Parsing financial spreadsheet…"):
                    try:
                        payload = load_private_company_data(
                            file_bytes=csv_file.getvalue(),
                            filename=csv_file.name,
                            company_name=company_name_input.strip(),
                            currency=currency_input,
                        )
                        _, written_path, agent_paths = payload_to_agent_files(payload, output_dir="output")
                    except Exception as exc:
                        st.error(f"CSV ingestion failed: {exc}")
                        st.stop()
                st.session_state["ocr_cache"] = {
                    "cache_key": cache_key, "payload": payload,
                    "written_path": written_path, "agent_paths": agent_paths,
                    "source_label": f"Private Upload · {csv_file.name}",
                }
                st.session_state.pop("agent_outputs", None)
                fields_loaded = [k for k, v in payload.get("time_series", {}).items() if v]
                st.success(f"Loaded **{company_name_input.strip()}** — {len(fields_loaded)} fields: {', '.join(fields_loaded[:6])}{'…' if len(fields_loaded) > 6 else ''}")

    # ── Tab 4: Account Aggregator (AA) / RBI Consented Data ──────────────────
    with tab_aa:
        st.markdown(
            '<div style="background:#0A1020;border:1px solid #00BFFF33;border-left:3px solid #00BFFF;'
            'border-radius:4px;padding:10px 16px;margin-bottom:12px;">'
            '<div style="font-size:10px;font-weight:700;color:#00BFFF;letter-spacing:0.1em;margin-bottom:4px;">'
            'RBI ACCOUNT AGGREGATOR (AA) FRAMEWORK</div>'
            '<div style="font-size:11px;color:#AAAAAA;line-height:1.6;">'
            'The AA ecosystem (Sahamati / FinSAT) lets a Financial Information User (FIU) fetch '
            'bank/financial data with explicit user consent via a registered Account Aggregator. '
            'This tab accepts exported FI data in the ReBIT DEPOSIT schema — the same format '
            'your AA provider delivers after consent is granted.<br><br>'
            '<span style="color:#FF6B35;">POC Note:</span> '
            'Production AA integration requires FIU registration with RBI. '
            'This implementation accepts the decrypted JSON payload for research and testing.'
            '</div></div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<p style="font-size:11px;color:#666;font-family:monospace;">'
            '▸ Upload the decrypted ReBIT FI DEPOSIT JSON exported from your AA provider. '
            'Credits are aggregated per quarter as a revenue proxy. '
            'Download the sample below to see the expected structure.</p>',
            unsafe_allow_html=True,
        )

        st.download_button(
            label="⬇  Download Sample AA FI JSON",
            data=aa_sample_json(),
            file_name="sample_aa_deposit.json",
            mime="application/json",
            key="aa_sample_dl",
        )

        col_aa1, col_aa2 = st.columns([2, 1])
        aa_company_name = col_aa1.text_input(
            "Entity / Company Name", placeholder="e.g. Acme Pvt. Ltd.",
            label_visibility="visible", key="aa_company_name",
        )
        aa_currency = col_aa2.selectbox(
            "Currency", ["INR", "USD", "EUR", "GBP", "JPY", "SGD", "AED"],
            key="aa_currency",
        )
        aa_file = st.file_uploader(
            "Upload ReBIT FI DEPOSIT JSON",
            type=["json"],
            label_visibility="collapsed",
            key="aa_uploader",
        )

        if aa_file and st.button("⬆  Load AA Consented Data", key="load_aa_btn"):
            if not aa_company_name.strip():
                st.warning("Please enter the entity name before loading.")
            else:
                cache_key = ("aa", aa_file.name, aa_company_name.strip())
                with st.spinner("Parsing AA FI data…"):
                    try:
                        payload = parse_aa_deposit(
                            file_bytes=aa_file.getvalue(),
                            company_name=aa_company_name.strip(),
                            currency=aa_currency,
                        )
                        _, written_path, agent_paths = payload_to_agent_files(payload, output_dir="output")
                    except Exception as exc:
                        st.error(f"AA ingestion failed: {exc}")
                        st.stop()
                st.session_state["ocr_cache"] = {
                    "cache_key": cache_key, "payload": payload,
                    "written_path": written_path, "agent_paths": agent_paths,
                    "source_label": f"AA Consented · {aa_file.name}",
                }
                st.session_state.pop("agent_outputs", None)
                fields_loaded = [k for k, v in payload.get("time_series", {}).items() if v]
                st.success(
                    f"Loaded **{aa_company_name.strip()}** via AA — "
                    f"{len(fields_loaded)} fields: {', '.join(fields_loaded)}"
                )

    # ── Shared section below all tabs ─────────────────────────────────────────
    cached = st.session_state.get("ocr_cache", {})
    if not cached:
        return

    payload    = cached["payload"]
    agent_paths = cached["agent_paths"]
    written_path = cached["written_path"]
    source_label = cached.get("source_label", written_path.name)

    render_hr()
    render_section_header("Extracted Key Metrics", subtitle=f"Source: {source_label}")
    render_metric_cards(payload)

    with st.expander("Raw Data Preview", expanded=False):
        st.dataframe(_preview_df(payload), use_container_width=True)

    # ── Data Credibility Panel ────────────────────────────────────────────────
    render_hr()
    render_section_header("Data Credibility Score",
                          subtitle="Automated checks on source authenticity, consistency, and completeness")

    _cache_key = cached.get("cache_key", (None,))
    _src_type  = _cache_key[0] if isinstance(_cache_key, tuple) else "csv"
    _ticker_for_verify = _cache_key[1] if (isinstance(_cache_key, tuple) and _src_type == "ticker") else None

    # Map internal key to verifier source string
    _source_map = {"pdf": "bloomberg_pdf", "ticker": "ticker", "csv": "csv"}
    _verifier_source = _source_map.get(_src_type, "csv")

    with st.spinner("Running credibility checks…"):
        _report = run_verification(
            source=_verifier_source,
            payload=payload,
            ticker=_ticker_for_verify,
            fmp_api_key=fmp_api_key or "",
        )
    st.session_state["last_credibility_score"] = _report.score
    st.session_state["last_source_type"] = _verifier_source
    _render_credibility_panel(_report)

    render_hr()
    _render_agent_status_badges(payload, news_api_key)

    # ── Smart Data Readiness Alert ────────────────────────────────────────────
    render_hr()
    _avail        = _available_fields(payload)
    _req_liq      = {"current_assets", "current_liabilities", "total_assets", "total_liabilities", "equity"}
    _req_bs       = {"total_assets", "total_liabilities", "equity"}
    _missing_liq  = sorted(_req_liq - _avail)
    _missing_bs   = sorted(_req_bs  - _avail)
    _all_missing  = sorted(set(_missing_liq) | set(_missing_bs))

    if not _all_missing:
        # All good — show green status and go straight to Run
        st.markdown(
            '<div style="background:#001A0D;border:1px solid #00FF8833;border-left:4px solid #00FF88;'
            'border-radius:4px;padding:10px 16px;margin:4px 0;">'
            '<span style="color:#00FF88;font-size:12px;font-weight:600;">✅ All required data present</span>'
            '&nbsp;&nbsp;<span style="font-size:10px;color:#555;">All agents are ready to run the full analysis.</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        render_section_header("Run Agent Pipeline")
        if st.button("▶  RUN FULL ANALYSIS", use_container_width=False, key="run_pipeline_btn"):
            _cfg_err = _llm_config_error(base_url=base_url, api_key=api_key)
            if _cfg_err:
                st.error(f"LLM configuration error: {_cfg_err}")
                st.stop()
            _run_agent_pipeline(payload, agent_paths, base_url, model, api_key, news_api_key)

    else:
        # Missing fields — show amber alert with two choices
        _skipped_agents = []
        if _missing_liq:
            _skipped_agents.append("Liquidity Agent")
        if _missing_bs:
            _skipped_agents.append("Balance Sheet Agent")
        _skipped_agents.append("Cross Reference Agent")

        st.markdown(
            f'<div style="background:#1A1000;border:1px solid #FFB00044;border-left:4px solid #FFB000;'
            f'border-radius:4px;padding:10px 16px;margin:4px 0;">'
            f'<span style="color:#FFB000;font-size:12px;font-weight:600;">⚠️ Incomplete Data Detected</span><br>'
            f'<span style="font-size:10px;color:#999;">Missing fields: <b style="color:#FFB000;">'
            f'{", ".join(_all_missing)}</b></span><br>'
            f'<span style="font-size:10px;color:#666;">These agents will be skipped: '
            f'{", ".join(_skipped_agents)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        col_proceed, col_fix = st.columns([1, 1])
        _proceed_anyway = col_proceed.button(
            "▶  Proceed Anyway (skip missing agents)",
            key="run_pipeline_skip_btn",
            help="Run available agents now. Missing agents will be skipped.",
        )
        _fix_clicked = col_fix.button(
            "✏️  Fix Missing Data",
            key="toggle_supplement_btn",
            help="Auto-fetch or manually enter the missing fields before running.",
        )

        if _fix_clicked:
            st.session_state["show_supplement"] = True
        if _proceed_anyway:
            st.session_state.pop("show_supplement", None)

        # Only show the supplement form when user explicitly asked for it
        if st.session_state.get("show_supplement"):
            payload, agent_paths, written_path = _render_missing_data_supplement(
                payload, agent_paths, written_path, source_label,
                fmp_api_key=fmp_api_key,
                av_api_key=av_api_key,
            )

        # Run pipeline (either via proceed-anyway or after fixing data)
        if _proceed_anyway:
            _cfg_err = _llm_config_error(base_url=base_url, api_key=api_key)
            if _cfg_err:
                st.error(f"LLM configuration error: {_cfg_err}")
                st.stop()
            _run_agent_pipeline(payload, agent_paths, base_url, model, api_key, news_api_key)

    outputs = st.session_state.get("agent_outputs")
    if outputs:
        render_section_header("Agent Status Summary")
        for label, key, variant in [
            ("Revenue Agent", "revenue", ""),
            ("Liquidity Agent", "liquidity", "liq"),
            ("Balance Sheet Agent", "balance_sheet", "bs"),
            ("Sentiment Agent", "sentiment", ""),
            ("Cross Reference Agent", "cross_reference", "xref"),
        ]:
            render_agent_card(label, outputs.get(key, {}), css_variant=variant)



# ── Page 2 ────────────────────────────────────────────────────────────────────

def page_workflow() -> None:
    render_section_header("Agent Pipeline Architecture", subtitle="Hover over nodes to inspect outputs")

    outputs = st.session_state.get("agent_outputs") or {}

    st.markdown("""
        <div class="bb-workflow-legend">
            <div class="bb-legend-item"><span class="bb-legend-dot" style="background:#4A4A5A"></span>I/O Nodes</div>
            <div class="bb-legend-item"><span class="bb-legend-dot" style="background:#0D3B66"></span>OCR Parser</div>
            <div class="bb-legend-item"><span class="bb-legend-dot" style="background:#3B2800"></span>Revenue Agent</div>
            <div class="bb-legend-item"><span class="bb-legend-dot" style="background:#003040"></span>Liquidity Agent</div>
            <div class="bb-legend-item"><span class="bb-legend-dot" style="background:#3B1800"></span>Balance Sheet Agent</div>
            <div class="bb-legend-item"><span class="bb-legend-dot" style="background:#2A0040"></span>Sentiment Agent</div>
            <div class="bb-legend-item"><span class="bb-legend-dot" style="background:#002010"></span>Cross Reference</div>
        </div>""", unsafe_allow_html=True)

    nodes = [
        # ── Data sources (3 paths) ──────────────────────────────────────────
        Node(id="pdf",    label="Bloomberg\nPDF",          color="#1A1A2E", shape="box",     size=20, font={"color":"#CCCCCC","size":12}, title="Bloomberg Financial Statement PDF(s) — upload via Tab 1"),
        Node(id="ticker", label="Ticker\n(yfinance)",       color="#1A1A2E", shape="box",     size=20, font={"color":"#00BFFF","size":12}, title="Listed company ticker (e.g. INFY.NS) — auto-fetches annual financials via yfinance"),
        Node(id="csv",    label="Private Co.\nCSV/Excel",   color="#1A1A2E", shape="box",     size=20, font={"color":"#FFB000","size":12}, title="Private/non-listed company — upload a structured CSV or Excel file"),
        Node(id="news",   label="News\nAPI",                color="#1A1A2E", shape="box",     size=20, font={"color":"#CC88FF","size":12}, title="NewsAPI — latest company news headlines (newsapi.org)"),
        # ── Ingestion / Schema converter ────────────────────────────────────
        Node(id="ingest", label="Ingestion\nLayer",         color="#0D3B66", shape="box",     size=22, font={"color":"#00BFFF","size":12}, title="<b>Ingestion Layer</b><br>PDF → OCR parser · Ticker → yfinance · CSV → structured parser<br>All converge to same internal JSON schema → output/"),
        # ── Deterministic agents ─────────────────────────────────────────────
        Node(id="rev",    label="Revenue\nAgent",           color="#3B2800", shape="ellipse", size=22, font={"color":"#FFB000","size":12}, title=agent_tooltip_html("Revenue Agent",       outputs.get("revenue"))),
        Node(id="liq",    label="Liquidity\nAgent",         color="#003040", shape="ellipse", size=22, font={"color":"#00BFFF","size":12}, title=agent_tooltip_html("Liquidity Agent",     outputs.get("liquidity"))),
        Node(id="bs",     label="Balance Sheet\nAgent",     color="#3B1800", shape="ellipse", size=22, font={"color":"#FF6B35","size":12}, title=agent_tooltip_html("Balance Sheet Agent", outputs.get("balance_sheet"))),
        Node(id="sent",   label="Sentiment\nAgent",         color="#2A0040", shape="ellipse", size=22, font={"color":"#CC88FF","size":12}, title=agent_tooltip_html("Sentiment Agent",     outputs.get("sentiment"))),
        # ── LLM synthesis ────────────────────────────────────────────────────
        Node(id="cross",  label="Cross\nReference\nAgent",  color="#002010", shape="box",     size=24, font={"color":"#00FF88","size":12}, title=agent_tooltip_html("Cross Reference Agent",outputs.get("cross_reference"))),
        Node(id="out",    label="Explainable\nOutput",       color="#1A1A2E", shape="box",     size=20, font={"color":"#E6E6E6","size":12}, title="Final explainable financial analysis report"),
    ]
    edges = [
        # 3 sources → ingestion layer
        Edge(source="pdf",    target="ingest", color="#555566", width=2),
        Edge(source="ticker", target="ingest", color="#00BFFF", width=2),
        Edge(source="csv",    target="ingest", color="#FFB000", width=2),
        # news → sentiment
        Edge(source="news",   target="sent",   color="#CC88FF", width=2),
        # ingestion layer → deterministic agents
        Edge(source="ingest", target="rev",    color="#FFB000", width=1),
        Edge(source="ingest", target="liq",    color="#00BFFF", width=1),
        Edge(source="ingest", target="bs",     color="#FF6B35", width=1),
        # agents → cross-reference (LLM)
        Edge(source="rev",    target="cross",  color="#FFB000", width=1, dashes=True),
        Edge(source="liq",    target="cross",  color="#00BFFF", width=1, dashes=True),
        Edge(source="bs",     target="cross",  color="#FF6B35", width=1, dashes=True),
        Edge(source="sent",   target="cross",  color="#CC88FF", width=1, dashes=True),
        Edge(source="cross",  target="out",    color="#00FF88", width=2),
    ]
    config = Config(width="100%", height=520, directed=True, physics=False, hierarchical=True,
                    hierarchical_sort_method="directed", nodeHighlightBehavior=True, highlightColor="#FFB000", collapsible=False)
    agraph(nodes=nodes, edges=edges, config=config)

    render_hr()
    if outputs:
        render_section_header("Agent Output Detail", subtitle="Expanded metrics per agent")
        c1, c2 = st.columns(2)
        with c1:
            render_agent_card("Revenue Agent",       outputs.get("revenue", {}),       css_variant="")
            render_agent_card("Balance Sheet Agent", outputs.get("balance_sheet", {}), css_variant="bs")
            render_agent_card("Sentiment Agent",     outputs.get("sentiment", {}),     css_variant="")
        with c2:
            render_agent_card("Liquidity Agent",     outputs.get("liquidity", {}),     css_variant="liq")
            render_cross_ref_card(outputs.get("cross_reference", {}))
    else:
        st.markdown('<div style="color:#444;font-size:11px;margin-top:12px;">▸ Run analysis on the Upload page to populate node tooltips.</div>', unsafe_allow_html=True)


# ── Meta-Orchestrator panel ───────────────────────────────────────────────────

def _render_meta_panel(meta: dict | None) -> None:
    """Render the self-aware meta-assessment panel on the Financial Analysis page."""
    if not meta:
        return

    overall = meta.get("overall_confidence", 0)
    label   = meta.get("confidence_label", "—")
    colour  = {"HIGH": "#00FF88", "MEDIUM": "#FFB000", "LOW": "#C94A3A"}.get(label, "#666")
    succeeded = meta.get("agents_succeeded", 0)
    assessed  = meta.get("agents_assessed", 5)

    render_section_header(
        "Meta-Orchestrator Assessment",
        subtitle="Self-aware confidence scoring · drift detection · guardrail audit",
    )

    # Overall confidence badge
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:20px;margin-bottom:12px;">'
        f'<div style="background:#0A1020;border:2px solid {colour};border-radius:6px;'
        f'padding:10px 20px;text-align:center;">'
        f'<div style="font-size:9px;color:{colour};letter-spacing:0.15em;font-weight:700;">OVERALL CONFIDENCE</div>'
        f'<div style="font-size:28px;font-weight:700;color:{colour};line-height:1.1;">{overall}</div>'
        f'<div style="font-size:10px;color:{colour};letter-spacing:0.1em;">{label}</div>'
        f'</div>'
        f'<div style="font-size:11px;color:#888;line-height:1.8;">'
        f'{succeeded}/{assessed} agents succeeded<br>'
        f'{len(meta.get("drift_alerts", []))} drift alert(s)<br>'
        f'{len(meta.get("flags", []))} flag(s) raised'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Per-agent confidence bars
    per = meta.get("per_agent_confidence", {})
    if per:
        bar_cols = st.columns(len(per))
        _agent_labels = {
            "revenue": "Revenue", "liquidity": "Liquidity",
            "balance_sheet": "Bal. Sheet", "sentiment": "Sentiment",
            "cross_reference": "Cross Ref",
        }
        for col, (key, score) in zip(bar_cols, per.items()):
            c = "#00FF88" if score >= 80 else "#FFB000" if score >= 55 else "#C94A3A" if score > 0 else "#333"
            col.markdown(
                f'<div style="text-align:center;">'
                f'<div style="font-size:9px;color:#666;margin-bottom:3px;">{_agent_labels.get(key, key)}</div>'
                f'<div style="background:#111;border-radius:3px;height:6px;margin-bottom:3px;">'
                f'<div style="background:{c};height:6px;border-radius:3px;width:{score}%;"></div>'
                f'</div>'
                f'<div style="font-size:10px;color:{c};font-weight:700;">{score}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Flags and drift alerts
    flags = meta.get("flags", [])
    if flags:
        st.markdown("<br>", unsafe_allow_html=True)
        for flag in flags:
            icon = "⚠" if flag.startswith(("DRIFT", "GUARDRAIL")) else "▸"
            fc = "#FFB000" if "DRIFT" in flag else "#C94A3A" if "GUARDRAIL" in flag else "#888"
            st.markdown(
                f'<div style="font-size:11px;color:{fc};padding:2px 0;">{icon} {flag}</div>',
                unsafe_allow_html=True,
            )

    # LLM advisory (if generated)
    advisory = meta.get("advisory", "")
    if advisory:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            f'<div style="background:#0A1020;border-left:3px solid #00BFFF;border-radius:4px;'
            f'padding:10px 14px;">'
            f'<div style="font-size:9px;color:#00BFFF;font-weight:700;letter-spacing:0.1em;'
            f'margin-bottom:6px;">META-ORCHESTRATOR ADVISORY</div>'
            f'<div style="font-size:11px;color:#CCCCCC;line-height:1.7;">{advisory}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    elif meta.get("advisory_error"):
        st.caption(f"Advisory generation failed: {meta['advisory_error'][:120]}")


# ── Page 3 ────────────────────────────────────────────────────────────────────

def page_analysis() -> None:
    render_section_header("Financial Analysis Output", subtitle="Deterministic metrics + LLM explanations")

    st.markdown(
        '<div style="background:#1A0D00;border:1px solid #FF6B3544;border-left:4px solid #FF6B35;'
        'border-radius:4px;padding:10px 16px;margin:0 0 16px 0;">'
        '<span style="color:#FF6B35;font-size:11px;font-weight:700;letter-spacing:0.08em;">'
        'NOT A CREDIT DECISION</span>'
        '<span style="font-size:10px;color:#999;margin-left:12px;">'
        'This output is an analytical aid only. It does not constitute a credit, lending, or investment '
        'decision. All outputs require human review before informing any financial determination. '
        'RBI Digital Lending Guidelines 2022 &middot; DPDP Act 2023'
        '</span></div>',
        unsafe_allow_html=True,
    )

    outputs = st.session_state.get("agent_outputs")
    if not outputs:
        st.markdown('<div style="color:#444;font-size:12px;">▸ No analysis data yet. Upload PDFs and run the pipeline first.</div>', unsafe_allow_html=True)
        return

    entity = outputs.get("entity", "—")
    st.markdown(f'<div style="font-size:10px;color:#555;margin-bottom:16px;">ENTITY: <span style="color:#FFB000;">{entity.upper()}</span></div>', unsafe_allow_html=True)

    _render_meta_panel(st.session_state.get("meta_assessment"))

    render_hr()
    c1, c2 = st.columns(2)
    with c1:
        render_section_header("Revenue Agent", subtitle="Income Statement Analysis")
        render_agent_card("Revenue Agent", outputs.get("revenue", {}), css_variant="", icon="◆")
    with c2:
        render_section_header("Liquidity Agent", subtitle="Working Capital & Funding Stability")
        render_agent_card("Liquidity Agent", outputs.get("liquidity", {}), css_variant="liq", icon="◈")

    render_hr()

    c3, c4 = st.columns(2)
    with c3:
        render_section_header("Balance Sheet Agent", subtitle="Leverage & Asset Growth")
        render_agent_card("Balance Sheet Agent", outputs.get("balance_sheet", {}), css_variant="bs", icon="◇")
    with c4:
        render_section_header("Sentiment Agent", subtitle="Public Perception from Latest News")
        render_agent_card("Sentiment Agent", outputs.get("sentiment", {}), css_variant="", icon="◉")

    render_hr()
    render_section_header("Cross Reference Agent", subtitle="Integrated Explainable Summary — Financial + Sentiment")
    render_cross_ref_card(outputs.get("cross_reference", {}))

    render_hr()
    render_section_header("Raw Agent Outputs", subtitle="Full JSON — audit trail")
    for label, key in [
        ("Revenue Agent", "revenue"), ("Liquidity Agent", "liquidity"),
        ("Balance Sheet Agent", "balance_sheet"), ("Sentiment Agent", "sentiment"),
        ("Cross Reference Agent", "cross_reference"),
    ]:
        with st.expander(f"{label}"):
            st.json(outputs.get(key, {}))


# ── Page 4 ────────────────────────────────────────────────────────────────────

def page_basel() -> None:
    render_section_header("Basel III Risk Governance Alignment", subtitle="How this system supports regulatory frameworks")

    st.markdown("""
        <div class="bb-basel-panel">
            <div class="bb-section-title" style="margin-bottom:12px;">System Overview</div>
            <p class="bb-body-text">This Explainable Financial Analysis System supports Basel III-aligned risk governance
            workflows. It provides transparent, auditable, and explainable financial risk indicators derived from
            structured Bloomberg financial statements. All numeric computations are performed deterministically in Python —
            the LLM is used exclusively for natural-language explanation of pre-computed metrics, ensuring full auditability.</p>
        </div>

        <div class="bb-basel-panel">
            <div class="bb-section-title" style="margin-bottom:12px;">Regulatory Pillar Alignment</div>
            <span class="bb-pillar-badge">Pillar 2</span>
            <p class="bb-body-text" style="margin-top:8px;">Supports <b>Pillar 2 supervisory monitoring</b> by providing
            structured, explainable outputs for internal credit risk review. Revenue trends, liquidity ratios, and
            balance sheet leverage metrics are presented with full transparency, enabling risk officers to trace every
            figure back to its source data.</p>
            <span class="bb-pillar-badge" style="border-color:#00BFFF;color:#00BFFF;background:#001A2E;">Pillar 3</span>
            <p class="bb-body-text" style="margin-top:8px;">Explainability of outputs aligns with <b>Pillar 3 market
            discipline</b> requirements. The cross-reference agent produces integrated narratives bridging quantitative
            metrics with qualitative risk language.</p>
        </div>

        <div class="bb-basel-panel">
            <div class="bb-section-title" style="margin-bottom:12px;">Scope &amp; Limitations</div>
            <p class="bb-body-text"><span style="color:#FF6B35;">⚠ Important:</span> This system does <b>not</b>
            calculate regulatory capital adequacy ratios, Tier 1/Tier 2 capital buffers, LCR, NSFR, or any other
            binding Basel III regulatory measure. It is not a substitute for regulatory reporting or prudential supervision.</p>
            <p class="bb-body-text">Intended use cases:</p>
            <ul style="font-size:12px;color:#CCCCCC;line-height:1.8;padding-left:20px;">
                <li>Structured financial statement review workflows</li>
                <li>Preliminary credit background checks based on public filings</li>
                <li>Risk trend monitoring across multiple reporting periods</li>
                <li>Generation of explainable, auditable financial summaries</li>
            </ul>
        </div>

        <div class="bb-basel-panel">
            <div class="bb-section-title" style="margin-bottom:14px;">Agent → Framework Mapping</div>
            <div class="bb-metric-row">
                <span class="bb-mkey" style="color:#FFB000;">Revenue Agent</span>
                <span class="bb-mval" style="font-size:11px;">Income stability · Earnings trend analysis</span>
            </div>
            <div class="bb-metric-row">
                <span class="bb-mkey" style="color:#00BFFF;">Liquidity Agent</span>
                <span class="bb-mval" style="font-size:11px;">Working capital adequacy · LCR-adjacent indicators</span>
            </div>
            <div class="bb-metric-row">
                <span class="bb-mkey" style="color:#FF6B35;">Balance Sheet Agent</span>
                <span class="bb-mval" style="font-size:11px;">Leverage ratio monitoring · Asset quality signals</span>
            </div>
            <div class="bb-metric-row">
                <span class="bb-mkey" style="color:#00FF88;">Cross Reference Agent</span>
                <span class="bb-mval" style="font-size:11px;">Integrated risk narrative · Pillar 2 reporting aid</span>
            </div>
        </div>
    """, unsafe_allow_html=True)


# ── Page 5 ────────────────────────────────────────────────────────────────────

def page_compliance() -> None:
    render_section_header(
        "Compliance & Audit Trail",
        subtitle="DPDP Act 2023 · RBI IT Framework · Queryable SQLite + Tamper-Evident JSONL",
    )

    # ── Consent status ────────────────────────────────────────────────────────
    consent_ts = st.session_state.get("consent_timestamp", "")
    if consent_ts:
        st.markdown(
            f'<div style="background:#001A0D;border:1px solid #3AB87A44;border-left:3px solid #3AB87A;'
            f'border-radius:4px;padding:8px 14px;margin-bottom:12px;">'
            f'<span style="color:#3AB87A;font-size:11px;font-weight:700;">DPDP CONSENT ACTIVE</span>'
            f'<span style="font-size:10px;color:#888;margin-left:10px;">Recorded: {consent_ts}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="background:#1A0000;border-left:3px solid #C94A3A;padding:8px 14px;margin-bottom:12px;">'
            '<span style="color:#C94A3A;font-size:11px;">No consent timestamp found in this session.</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    render_hr()

    # ── SQLite run history ────────────────────────────────────────────────────
    render_section_header(
        "Analysis Run History",
        subtitle="output/finveritas.db — queryable with DB Browser for SQLite",
    )

    runs = _db.query_runs()
    if not runs:
        st.markdown('<div style="color:#444;font-size:11px;">No analysis runs recorded yet. Run an analysis on the Upload page first.</div>', unsafe_allow_html=True)
    else:
        # Summary table
        summary_rows = []
        for r in runs:
            summary_rows.append({
                "Run ID": (r.get("run_id") or "")[:8] + "…",
                "Timestamp (UTC)": (r.get("ts") or "")[:19].replace("T", " "),
                "Entity": r.get("entity", "—"),
                "Source": r.get("source_type", "—"),
                "Credibility": r.get("credibility_score"),
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        render_hr()

        # Per-run drilldown
        render_section_header("Run Drilldown", subtitle="Full agent metrics, calculations, and LLM call log")
        for r in runs:
            run_id_short = (r.get("run_id") or "")[:8]
            ts_short = (r.get("ts") or "")[:19].replace("T", " ")
            entity = r.get("entity", "—")
            with st.expander(f"{ts_short}  ·  {entity}  ·  {run_id_short}…", expanded=False):
                # Metadata
                col1, col2, col3 = st.columns(3)
                col1.metric("Source", r.get("source_type", "—"))
                col2.metric("Credibility Score", r.get("credibility_score") or "—")
                col3.metric("Input Hash", (r.get("input_hash") or "—")[:12] + "…")

                st.markdown(f'<div style="font-size:9px;color:#444;font-family:monospace;margin:4px 0;">run_id: {r.get("run_id")} · consent: {r.get("consent_timestamp") or "—"}</div>', unsafe_allow_html=True)

                # Agent executions
                agents = _db.query_run_agents(r["run_id"])
                if agents:
                    st.markdown("**Agent Executions**")
                    agent_rows = []
                    for a in agents:
                        agent_rows.append({
                            "Agent": a.get("agent_name", "—"),
                            "Status": a.get("status", "—"),
                            "Duration (ms)": a.get("duration_ms"),
                            "Error": (a.get("error_message") or "")[:60] or "—",
                        })
                    st.dataframe(pd.DataFrame(agent_rows), use_container_width=True, hide_index=True)

                    for a in agents:
                        if a.get("metrics_json"):
                            with st.expander(f"Metrics — {a['agent_name']}", expanded=False):
                                try:
                                    st.json(json.loads(a["metrics_json"]))
                                except Exception:
                                    st.code(a["metrics_json"])
                        if a.get("analysis_text"):
                            with st.expander(f"LLM Narrative — {a['agent_name']}", expanded=False):
                                st.markdown(
                                    f'<div style="font-size:11px;color:#CCCCCC;line-height:1.6;">{a["analysis_text"]}</div>',
                                    unsafe_allow_html=True,
                                )

                # LLM calls
                llm_calls = _db.query_run_llm_calls(r["run_id"])
                if llm_calls:
                    st.markdown("**LLM Call Log**")
                    for lc in llm_calls:
                        label = f"[{lc.get('agent_name')}] attempt {lc.get('attempt', 1)} · {lc.get('model', '—')} · {lc.get('duration_ms', '?')}ms"
                        if lc.get("violations_found"):
                            label += " ⚠ guardrail triggered"
                        with st.expander(label, expanded=False):
                            st.markdown("**System Prompt**")
                            st.code(lc.get("system_prompt") or "", language="text")
                            st.markdown("**Human Prompt**")
                            st.code(lc.get("human_prompt") or "", language="json")
                            st.markdown("**Response**")
                            st.code(lc.get("response_text") or "", language="text")
                            if lc.get("violations_found"):
                                st.markdown(
                                    f'<div style="color:#FFB000;font-size:10px;">Violations: {lc["violations_found"]}</div>',
                                    unsafe_allow_html=True,
                                )

    render_hr()

    # ── JSONL chain integrity ─────────────────────────────────────────────────
    render_section_header("Tamper-Evident Chain (JSONL)", subtitle="output/audit_log.jsonl — SHA-256 hash chain")

    entries = audit_read_log()
    chain_violations = audit_verify_chain(entries)

    if chain_violations:
        st.error(f"{len(chain_violations)} chain integrity violation(s) detected")
        for v in chain_violations:
            st.markdown(f'<div style="font-size:10px;color:#C94A3A;font-family:monospace;">{v}</div>', unsafe_allow_html=True)
    elif entries:
        st.markdown(
            f'<div style="background:#001A0D;border-left:3px solid #3AB87A;padding:6px 12px;">'
            f'<span style="color:#3AB87A;font-size:10px;font-weight:700;">✔ Chain intact</span>'
            f'<span style="font-size:10px;color:#666;margin-left:8px;">{len(entries)} entr{"y" if len(entries)==1 else "ies"} · all hashes verified</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div style="color:#444;font-size:11px;">No JSONL entries yet.</div>', unsafe_allow_html=True)

    if entries:
        col_dl1, col_dl2 = st.columns([1, 3])
        col_dl1.download_button(
            label="⬇  audit_log.jsonl",
            data="\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
            file_name="finveritas_audit_log.jsonl",
            mime="application/jsonl",
            key="audit_dl",
        )
        with st.expander("Raw JSONL", expanded=False):
            log_path = Path("output/audit_log.jsonl")
            if log_path.exists():
                st.code(log_path.read_text(encoding="utf-8"), language="json")

    render_hr()

    # ── Regulatory alignment ──────────────────────────────────────────────────
    render_section_header("Regulatory Alignment Summary", subtitle="What each feature satisfies")
    st.markdown("""
        <table style="font-size:11px;color:#CCCCCC;width:100%;border-collapse:collapse;">
        <thead><tr>
            <th style="text-align:left;color:#FFB000;padding:6px 10px;border-bottom:1px solid #222;">Requirement</th>
            <th style="text-align:left;color:#FFB000;padding:6px 10px;border-bottom:1px solid #222;">Framework</th>
            <th style="text-align:left;color:#3AB87A;padding:6px 10px;border-bottom:1px solid #222;">Implementation</th>
        </tr></thead>
        <tbody>
        <tr><td style="padding:5px 10px;">Explicit consent before data processing</td>
            <td style="padding:5px 10px;color:#888;">DPDP §6</td>
            <td style="padding:5px 10px;color:#3AB87A;">Consent gate on first load; timestamp stored</td></tr>
        <tr><td style="padding:5px 10px;">Right to erasure</td>
            <td style="padding:5px 10px;color:#888;">DPDP §13</td>
            <td style="padding:5px 10px;color:#3AB87A;">Delete All Data removes output files + session</td></tr>
        <tr><td style="padding:5px 10px;">No credit decisions from AI</td>
            <td style="padding:5px 10px;color:#888;">RBI DLG 2022</td>
            <td style="padding:5px 10px;color:#3AB87A;">Disclaimer banner + regex guardrail with retry</td></tr>
        <tr><td style="padding:5px 10px;">Full prompt/response audit trail</td>
            <td style="padding:5px 10px;color:#888;">RBI IT Framework</td>
            <td style="padding:5px 10px;color:#3AB87A;">SQLite llm_calls table — every prompt & response stored</td></tr>
        <tr><td style="padding:5px 10px;">Tamper-evident records</td>
            <td style="padding:5px 10px;color:#888;">RBI IT Framework §8</td>
            <td style="padding:5px 10px;color:#3AB87A;">SHA-256 chained JSONL — modification breaks verify_chain()</td></tr>
        <tr><td style="padding:5px 10px;">Queryable audit log</td>
            <td style="padding:5px 10px;color:#888;">RBI IT Framework</td>
            <td style="padding:5px 10px;color:#3AB87A;">SQLite (output/finveritas.db) — open with DB Browser</td></tr>
        <tr><td style="padding:5px 10px;">Data localization</td>
            <td style="padding:5px 10px;color:#888;">RBI Data Localisation</td>
            <td style="padding:5px 10px;color:#3AB87A;">All stores written to local output/ only</td></tr>
        <tr><td style="padding:5px 10px;">Consented financial data sourcing</td>
            <td style="padding:5px 10px;color:#888;">RBI AA Framework</td>
            <td style="padding:5px 10px;color:#3AB87A;">AA / RBI Consented Data tab (POC)</td></tr>
        <tr><td style="padding:5px 10px;">Explainable AI outputs</td>
            <td style="padding:5px 10px;color:#888;">RBI Pillar 2/3</td>
            <td style="padding:5px 10px;color:#3AB87A;">LLM narrates only pre-computed metrics; full JSON audit trail</td></tr>
        </tbody></table>
    """, unsafe_allow_html=True)


# ── DPDP helpers ─────────────────────────────────────────────────────────────

def _delete_session_data() -> None:
    """Delete every file written in this session and wipe all cached state."""
    cached = st.session_state.get("ocr_cache", {})
    paths: list[Path] = []
    if cached.get("written_path"):
        paths.append(Path(cached["written_path"]))
    for p in (cached.get("agent_paths") or {}).values():
        paths.append(Path(p))
    for p in paths:
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
    for key in ["ocr_cache", "agent_outputs", "supp_prefilled", "show_supplement", "confirm_delete"]:
        st.session_state.pop(key, None)


def _render_consent_gate() -> None:
    """Full-page DPDP consent gate. Calls st.stop() so nothing else renders."""
    st.markdown(
        '<div style="max-width:680px;margin:60px auto 0;">'
        '<div style="font-size:9px;color:#FFB000;letter-spacing:0.2em;margin-bottom:8px;">FINVERITAS · DATA PRIVACY NOTICE</div>'
        '<div style="font-size:22px;font-weight:700;color:#E6E6E6;margin-bottom:4px;">Before you begin</div>'
        '<div style="font-size:12px;color:#888;margin-bottom:24px;">Digital Personal Data Protection Act, 2023 (DPDP) — Consent Record</div>',
        unsafe_allow_html=True,
    )

    sections = [
        ("What data is processed",
         "Financial documents you upload (PDFs, CSV/Excel files) or ticker data fetched via Yahoo Finance. "
         "No data is collected about you personally."),
        ("Purpose of processing",
         "Financial background analysis — computing revenue, liquidity, and balance-sheet metrics for the "
         "entity described in the uploaded documents. The LLM receives <b>only pre-computed metric summaries</b>, "
         "never raw document content."),
        ("Where data is stored",
         "Processed JSON files are written to the <code>output/</code> folder on <b>this device only</b>. "
         "No uploads to any external server, except the LLM endpoint you configure in the sidebar "
         "(which receives metric dictionaries, not source documents)."),
        ("How long data is kept",
         "Until you click <b>Delete All Data</b> in the sidebar, or close/restart the app and manually "
         "remove the <code>output/</code> folder. There is no automatic remote retention."),
        ("Your rights under DPDP",
         "You may request erasure at any time using the <b>Delete All Data</b> button in the sidebar. "
         "For queries contact the Data Fiduciary at the email shown in your institution's privacy notice."),
    ]

    for title, body in sections:
        st.markdown(
            f'<div style="border-left:2px solid #FFB00033;padding:8px 14px;margin:6px 0;">'
            f'<div style="font-size:10px;font-weight:700;color:#FFB000;letter-spacing:0.1em;margin-bottom:3px;">{title.upper()}</div>'
            f'<div style="font-size:12px;color:#CCCCCC;line-height:1.6;">{body}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    c1 = st.checkbox(
        "I confirm I have the right to process the financial data I am about to upload "
        "(it is my own data, publicly available, or I hold appropriate authorisation).",
        key="consent_c1",
    )
    c2 = st.checkbox(
        "I understand that processed data is stored on this device in the output/ folder, "
        "and I consent to this for the purpose of financial analysis described above.",
        key="consent_c2",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button(
        "I Agree & Continue",
        disabled=not (c1 and c2),
        use_container_width=False,
        key="consent_submit_btn",
    ):
        st.session_state["dpdp_consent_given"] = True
        st.session_state["consent_timestamp"] = datetime.now(timezone.utc).isoformat()
        st.rerun()

    if not (c1 and c2):
        st.markdown(
            '<div style="font-size:10px;color:#555;margin-top:4px;">Both boxes must be ticked to continue.</div>',
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="FinVeritas — Financial Analysis Platform",
        page_icon="⬡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    load_css()

    # Read theme prefs from session_state (set by sidebar below)
    _light = st.session_state.get("light_mode", False)
    _fscale = st.session_state.get("font_scale", 1.0)
    inject_theme_vars(font_scale=_fscale, light_mode=_light)

    entity = "—"
    cached = st.session_state.get("ocr_cache", {})
    if cached:
        payload = cached.get("payload") or {}
        entity = str(payload.get("entity", {}).get("entity_id") or "—")

    render_top_bar(entity=entity)

    if not st.session_state.get("dpdp_consent_given"):
        _render_consent_gate()

    # Seed sidebar session defaults once per session.
    if "llm_provider" not in st.session_state:
        st.session_state["llm_provider"] = _DEFAULT_PROVIDER
    if "llm_base_url" not in st.session_state:
        st.session_state["llm_base_url"] = _DEFAULT_BASE_URL
    if "llm_model" not in st.session_state:
        st.session_state["llm_model"] = _DEFAULT_MODEL
    if "llm_api_key" not in st.session_state:
        st.session_state["llm_api_key"] = _DEFAULT_API_KEY
    if "news_api_key_input" not in st.session_state:
        st.session_state["news_api_key_input"] = _DEFAULT_NEWS_API_KEY
    if "fmp_api_key_input" not in st.session_state:
        st.session_state["fmp_api_key_input"] = _DEFAULT_FMP_KEY
    if "av_api_key_input" not in st.session_state:
        st.session_state["av_api_key_input"] = _DEFAULT_AV_KEY

    with st.sidebar:
        st.markdown("""
            <div class="bb-sidebar-logo">
                <div class="bb-sidebar-brand-mark">FV</div>
                <div>
                    <div class="bb-sidebar-logo-text">FinVeritas</div>
                    <div class="bb-sidebar-logo-sub">Financial Analysis</div>
                </div>
            </div>""", unsafe_allow_html=True)

        st.markdown('<div class="bb-nav-label">Navigation</div>', unsafe_allow_html=True)
        page = st.radio("",
            ["Upload Statement", "Agent Workflow", "Financial Analysis", "Basel III Alignment", "Compliance & Audit"],
            label_visibility="collapsed")

        render_hr()
        st.markdown('<div class="bb-nav-label" style="margin-top:8px;">Display</div>', unsafe_allow_html=True)
        theme_choice = st.radio("",
            ["Dark", "Light"],
            index=1 if _light else 0,
            horizontal=True,
            label_visibility="collapsed",
            key="theme_radio",
        )
        new_light = (theme_choice == "Light")
        if new_light != _light:
            st.session_state["light_mode"] = new_light
            st.rerun()
        font_scale = st.slider(
            "Font size", min_value=0.8, max_value=1.4, value=_fscale, step=0.1,
            format="%.1fx", key="font_scale_slider",
        )
        if font_scale != _fscale:
            st.session_state["font_scale"] = font_scale
            st.rerun()

        render_hr()
        st.markdown('<div class="bb-nav-label" style="margin-top:8px;">LLM Settings</div>', unsafe_allow_html=True)
        _providers = [
            "Local / OpenAI-compatible", "Gemini", "Groq",
            "vLLM (AMD ROCm)", "Other OpenAI-compatible",
        ]
        _provider_from_env = (_DEFAULT_PROVIDER or "").strip().lower()
        _provider_alias = {
            "local": "Local / OpenAI-compatible",
            "local / openai-compatible": "Local / OpenAI-compatible",
            "openai-compatible": "Other OpenAI-compatible",
            "openai compatible": "Other OpenAI-compatible",
            "gemini": "Gemini",
            "groq": "Groq",
            "vllm": "vLLM (AMD ROCm)",
            "vllm-rocm": "vLLM (AMD ROCm)",
            "rocm": "vLLM (AMD ROCm)",
        }
        _provider_default_label = _provider_alias.get(_provider_from_env, "Local / OpenAI-compatible")
        provider = st.selectbox(
            "LLM Provider",
            _providers,
            index=_providers.index(_provider_default_label),
            help="Pick Gemini for Google AI Studio, or use an OpenAI-compatible endpoint for local/cloud models.",
            key="llm_provider_select",
        )
        if provider == "Gemini":
            _provider_key = "gemini"
        elif provider == "Groq":
            _provider_key = "groq"
        elif provider == "vLLM (AMD ROCm)":
            _provider_key = "vllm-rocm"
        elif provider == "Other OpenAI-compatible":
            _provider_key = "openai-compatible"
        else:
            _provider_key = "local"
        provider_base_url, provider_model, provider_api_label = _provider_defaults(_provider_key)
        provider_env_api_key = _env_default_api_key(_provider_key)
        # If provider changed, update defaults only when fields are empty/placeholder.
        if st.session_state.get("llm_base_url") in {"", _DEFAULT_BASE_URL, "http://127.0.0.1:1234/v1"}:
            st.session_state["llm_base_url"] = provider_base_url
        if st.session_state.get("llm_model") in {"", _DEFAULT_MODEL, "qwen2.5-coder-1.5b-instruct-mlx"}:
            st.session_state["llm_model"] = provider_model
        if st.session_state.get("llm_api_key") in {"", _DEFAULT_API_KEY, "local", "API key", "Google AI Studio key", "Groq API key"}:
            st.session_state["llm_api_key"] = provider_env_api_key

        if st.button("Reload LLM defaults from .env", key="reload_llm_env_defaults"):
            st.session_state["llm_base_url"] = provider_base_url
            st.session_state["llm_model"] = provider_model
            st.session_state["llm_api_key"] = provider_env_api_key
            st.rerun()

        base_url = st.text_input("Base URL", value=st.session_state.get("llm_base_url", provider_base_url), key="llm_base_url")
        model    = st.text_input("Model", value=st.session_state.get("llm_model", provider_model), key="llm_model")
        api_key  = st.text_input(provider_api_label, value=st.session_state.get("llm_api_key", provider_env_api_key), type="password", key="llm_api_key")
        if provider == "Gemini":
            st.caption("Gemini is used through Google's OpenAI-compatible endpoint: https://generativelanguage.googleapis.com/v1beta/openai/")
        elif provider == "Groq":
            st.caption("Groq uses the OpenAI-compatible endpoint: https://api.groq.com/openai/v1")
        elif provider == "vLLM (AMD ROCm)":
            st.markdown(
                '<div style="background:#0D0020;border:1px solid #E8562044;border-left:3px solid #E85620;'
                'border-radius:4px;padding:8px 12px;margin-top:4px;">'
                '<div style="font-size:9px;color:#E85620;font-weight:700;letter-spacing:0.1em;">AMD ROCm / vLLM</div>'
                '<div style="font-size:10px;color:#AAA;line-height:1.6;margin-top:3px;">'
                'Start vLLM with ROCm support:<br>'
                '<code style="color:#E85620;font-size:9px;">'
                'HSA_OVERRIDE_GFX_VERSION=11.0.0 \\\n'
                'vllm serve Qwen/Qwen2.5-7B-Instruct \\\n'
                '  --dtype float16 --max-model-len 4096'
                '</code><br>'
                'See <b>requirements-rocm.txt</b> for setup.'
                '</div></div>',
                unsafe_allow_html=True,
            )

        render_hr()
        st.markdown('<div class="bb-nav-label" style="margin-top:8px;">News</div>', unsafe_allow_html=True)
        news_api_key = st.text_input(
            "NewsAPI Key", value=st.session_state.get("news_api_key_input", _DEFAULT_NEWS_API_KEY), type="password", key="news_api_key_input",
            help="Free key at newsapi.org — enables the Sentiment Agent",
        )

        render_hr()
        st.markdown('<div class="bb-nav-label" style="margin-top:8px;">Supplemental Sources</div>', unsafe_allow_html=True)
        st.markdown(
            '<p style="font-size:9px;color:var(--c-text3,#5A5A72);margin:2px 0 6px 0;">'
            "Auto-fill missing fields when yfinance data is incomplete.</p>",
            unsafe_allow_html=True,
        )
        fmp_api_key = st.text_input(
            "FMP Key", value=st.session_state.get("fmp_api_key_input", _DEFAULT_FMP_KEY), type="password", key="fmp_api_key_input",
            help="Free 250 req/day — financialmodelingprep.com",
        )
        st.markdown(
            '<a href="https://financialmodelingprep.com/developer/docs" target="_blank" '
            'style="font-size:9px;color:#444;">Get free FMP key ↗</a>',
            unsafe_allow_html=True,
        )
        av_api_key = st.text_input(
            "Alpha Vantage Key", value=st.session_state.get("av_api_key_input", _DEFAULT_AV_KEY), type="password", key="av_api_key_input",
            help="Free 25 req/day — alphavantage.co (backup source)",
        )
        st.markdown(
            '<a href="https://www.alphavantage.co/support/#api-key" target="_blank" '
            'style="font-size:9px;color:#444;">Get free AV key ↗</a>',
            unsafe_allow_html=True,
        )

        render_hr()
        has_data    = bool(st.session_state.get("ocr_cache"))
        has_results = bool(st.session_state.get("agent_outputs"))
        st.markdown(
            f'<div style="font-size:9px;color:#444;line-height:2;letter-spacing:0.05em;">'
            f'OCR DATA&nbsp;&nbsp; <span style="color:{"#00FF88" if has_data else "#333"}.">{"■ LOADED" if has_data else "□ NONE"}</span><br>'
            f'ANALYSIS&nbsp;&nbsp; <span style="color:{"#00FF88" if has_results else "#333"}.">{"■ READY" if has_results else "□ NONE"}</span>'
            f"</div>", unsafe_allow_html=True)

        render_hr()
        st.markdown('<div class="bb-nav-label" style="margin-top:8px;">Data & Privacy (DPDP)</div>', unsafe_allow_html=True)
        _consent_ts = st.session_state.get("consent_timestamp", "")
        if _consent_ts:
            st.markdown(
                f'<div style="font-size:9px;color:#3AB87A;margin-bottom:6px;">✔ Consent recorded {_consent_ts[:10]}</div>',
                unsafe_allow_html=True,
            )
        if st.button("Delete All Data", key="delete_data_btn", use_container_width=True):
            st.session_state["confirm_delete"] = True
        if st.session_state.get("confirm_delete"):
            st.warning("All uploaded files and analysis results on this device will be permanently deleted.")
            col_yes, col_no = st.columns(2)
            if col_yes.button("Yes, delete", key="confirm_delete_yes", use_container_width=True):
                _delete_session_data()
                st.rerun()
            if col_no.button("Cancel", key="confirm_delete_no", use_container_width=True):
                st.session_state.pop("confirm_delete", None)
                st.rerun()

    if "Upload" in page:
        page_upload(base_url, model, api_key, news_api_key,
                    fmp_api_key=fmp_api_key, av_api_key=av_api_key)
    elif "Workflow" in page:
        page_workflow()
    elif "Analysis" in page:
        page_analysis()
    elif "Basel" in page:
        page_basel()
    elif "Compliance" in page:
        page_compliance()


if __name__ == "__main__":
    main()
