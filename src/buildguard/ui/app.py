"""Chat-first Streamlit entry point with the full specialist workbench."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit as st

from buildguard.config import load_settings
from buildguard.ui.api_client import LocalApiClient
from buildguard.ui.chat import render_chat_page, render_session_sidebar
from buildguard.ui.workbench import WORKBENCH_PAGES


def _client() -> LocalApiClient:
    config_path = Path(os.environ.get("BUILDGUARD_CONFIG", "configs/app.yaml"))
    settings = load_settings(config_path)
    return LocalApiClient(str(settings.services.api_base_url))


def _apply_style() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1100px;
            padding-top: 1.4rem;
            padding-bottom: 3rem;
        }
        [data-testid="stChatMessage"] {
            border: 1px solid rgba(128, 128, 128, 0.18);
            border-radius: 14px;
            padding: 0.25rem 0.5rem;
        }
        [data-testid="stMetric"] {
            border: 1px solid rgba(128, 128, 128, 0.16);
            border-radius: 12px;
            padding: 0.7rem;
        }
        section[data-testid="stSidebar"] {
            background:
                radial-gradient(circle at 10% 5%, rgba(255, 78, 91, 0.13), transparent 28%),
                linear-gradient(180deg, #20232d 0%, #171922 100%);
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }
        section[data-testid="stSidebar"] .sidebar-brand {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin: 0.35rem 0 1.25rem;
            padding: 0.85rem 0.9rem;
            border: 1px solid rgba(255, 255, 255, 0.09);
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.035);
        }
        section[data-testid="stSidebar"] .brand-icon {
            display: grid;
            place-items: center;
            width: 2.35rem;
            height: 2.35rem;
            border-radius: 12px;
            background: linear-gradient(135deg, #ff4b5f, #ff7a45);
            box-shadow: 0 8px 22px rgba(255, 75, 95, 0.25);
        }
        section[data-testid="stSidebar"] .brand-name {
            font-size: 1.25rem;
            font-weight: 750;
            line-height: 1.2;
        }
        section[data-testid="stSidebar"] .brand-tagline {
            color: rgba(255, 255, 255, 0.55);
            font-size: 0.72rem;
            margin-top: 0.15rem;
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label {
            margin: 0.2rem 0;
            padding: 0.42rem 0.55rem;
            border: 1px solid transparent;
            border-radius: 11px;
            transition: all 120ms ease;
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background: rgba(255, 255, 255, 0.055);
            border-color: rgba(255, 255, 255, 0.08);
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
            background: rgba(255, 75, 95, 0.13);
            border-color: rgba(255, 75, 95, 0.35);
        }
        section[data-testid="stSidebar"] .stButton > button {
            border-radius: 11px;
            border-color: rgba(255, 255, 255, 0.09);
            text-align: left;
        }
        section[data-testid="stSidebar"] .stButton > button:hover {
            border-color: rgba(255, 75, 95, 0.45);
            color: #ffffff;
        }
        section[data-testid="stSidebar"] .service-pill {
            margin-top: 1rem;
            padding: 0.65rem 0.8rem;
            border-radius: 12px;
            background: rgba(43, 174, 102, 0.10);
            border: 1px solid rgba(73, 202, 126, 0.22);
            color: #8de1ae;
            font-size: 0.82rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_shell(client: LocalApiClient, health: dict[str, Any]) -> None:
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
          <div class="brand-icon">🛡️</div>
          <div>
            <div class="brand-name">BuildGuard</div>
            <div class="brand-tagline">施工安全智能体</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    pages = ["💬 智能对话", *WORKBENCH_PAGES]
    if st.session_state.get("workspace_page") not in {None, *pages}:
        st.session_state["workspace_page"] = pages[0]
    selected = st.sidebar.radio("工作区", pages, key="workspace_page")
    healthy = health.get("status") == "ok"
    status = "● 本地服务正常" if healthy else "● 本地服务降级"
    st.sidebar.markdown(
        f'<div class="service-pill">{status}</div>',
        unsafe_allow_html=True,
    )
    if selected == "💬 智能对话":
        render_session_sidebar(client)
        render_chat_page(client, health)
        return
    WORKBENCH_PAGES[selected](client)


def main() -> None:
    st.set_page_config(
        page_title="BuildGuard-Radeon",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _apply_style()
    try:
        client = _client()
        health = client.get("/health")
        _render_shell(client, health)
    except Exception as exc:
        st.error(f"本地 API 请求失败：{exc}")
        st.info("请确认 BuildGuard API 已在配置的本地地址启动，然后刷新页面。")


main()
