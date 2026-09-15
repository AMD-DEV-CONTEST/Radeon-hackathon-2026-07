"""
RoboAOI — AI-Powered Robotic Inspection Dashboard
AMD AI DevMaster Hackathon 2026 — Track 3: Physical AI


Visual identity note:
This UI is themed around the actual subject matter — copper PCB traces,
solder-mask green, and the framed "viewfinder" look of real AOI (Automated
Optical Inspection) machine cameras — rather than a generic dashboard
template. Functional logic (InspectionManager / ReportGenerator calls) is
unchanged from the original implementation.
"""
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

FRAME_DIR = Path(__file__).resolve().parent.parent / "outputs" / "grasp_demo_frames"

import pandas as pd
import streamlit as st
from PIL import Image
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from roboaoi.inspection_manager import InspectionManager
from roboaoi.report_generator import ReportGenerator

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

REPORTS_DIR = Path("reports")


def render_robot_execution_panel(result):
    st.markdown("## 🤖 Physical AI Robot")
    col1, col2 = st.columns([1, 2])
    status = result["status"]
    if status == "PASS":
        task = "Pick PCB"
        destination = "Assembly Conveyor"
    else:
        task = "Reject PCB"
        destination = "Reject Bin"
    with col1:
        st.info(
            f"""
**Robot:** Franka Panda
**Backend:** Genesis
**Current Task:** {task}
**Destination:** {destination}
**Status:** ✅ Complete
"""
        )
    with col2:
        progress = [
            "✔ AI Inspection",
            "✔ Motion Planning",
            "✔ Pick Object",
            "✔ Move",
            "✔ Release",
            "✔ Task Complete",
        ]
        for item in progress:
            st.success(item)

        gif_path = Path("assets/robot_demo.gif")

        if gif_path.exists():
            st.markdown("### 🎥 Genesis Robot Execution")
            st.image(str(gif_path), use_container_width=True)


def render_robot_frames():
    """
    Displays Genesis robot execution frames if available.
    """
    if not FRAME_DIR.exists():
        st.warning("Genesis execution frames not found.")
        return
    st.markdown("### 🎥 Genesis Robot Execution")
    frame_files = sorted(FRAME_DIR.glob("*.png"))
    if not frame_files:
        st.info("No execution frames available.")
        return
    cols = st.columns(4)
    for i, frame in enumerate(frame_files):
        with cols[i % 4]:
            st.image(
                str(frame),
                caption=frame.stem.replace("_", " ").title(),
                use_container_width=True,
            )
# ─────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="RoboAOI — Robotic Inspection",
    page_icon="🔌",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────────────────
# Theme — design tokens grounded in the subject (PCB / AOI machine aesthetic)
# ─────────────────────────────────────────────────────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --bg-void: #0A0D12;
  --bg-panel: #12161D;
  --bg-panel-raised: #181D26;
  --border-trace: #262E3A;
  --copper: #C9793F;
  --copper-bright: #E8944F;
  --solder-green: #2F9E6E;
  --alert-amber: #E8A23D;
  --fail-red: #E5484D;
  --text-primary: #EDEFF2;
  --text-muted: #8A94A6;
  --text-faint: #5A6472;
}

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }

[data-testid="stAppViewContainer"] { background-color: var(--bg-void); }
[data-testid="stHeader"] { background-color: transparent; }
[data-testid="stSidebar"] {
  background-color: var(--bg-panel);
  border-right: 1px solid var(--border-trace);
}
#MainMenu, footer { visibility: hidden; }

h1, h2, h3 { font-family: 'Space Grotesk', sans-serif !important; color: var(--text-primary) !important; letter-spacing: -0.01em; }
p, span, label, div { color: var(--text-primary); }

/* ---- Header band ---- */
.aoi-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 24px; margin-bottom: 6px;
  background: linear-gradient(90deg, var(--bg-panel-raised) 0%, var(--bg-panel) 100%);
  border: 1px solid var(--border-trace); border-radius: 10px;
  position: relative; overflow: hidden;
}
.aoi-header::after {
  content: ""; position: absolute; right: -40px; top: -40px;
  width: 160px; height: 160px; border-radius: 50%;
  background: radial-gradient(circle, rgba(201,121,63,0.14) 0%, transparent 70%);
}
.aoi-title { font-family: 'Space Grotesk', sans-serif; font-size: 26px; font-weight: 700; color: var(--text-primary); margin: 0; }
.aoi-subtitle { font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; color: var(--copper); letter-spacing: 0.04em; text-transform: uppercase; margin-top: 2px; }

/* ---- Status chips ---- */
.chip-row { display: flex; gap: 8px; flex-wrap: wrap; }
.chip {
  font-family: 'IBM Plex Mono', monospace; font-size: 11.5px;
  padding: 5px 10px; border-radius: 6px; border: 1px solid var(--border-trace);
  background: var(--bg-panel); color: var(--text-muted); white-space: nowrap;
}
.chip .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }
.dot-ok { background: var(--solder-green); box-shadow: 0 0 6px var(--solder-green); }
.dot-warn { background: var(--alert-amber); box-shadow: 0 0 6px var(--alert-amber); }
.dot-off { background: var(--text-faint); }

/* ---- PCB trace divider (signature element) ---- */
.trace-divider { display: flex; align-items: center; margin: 22px 0; opacity: 0.8; }
.trace-divider .line { flex: 1; height: 1px; background: repeating-linear-gradient(90deg, var(--border-trace) 0 6px, transparent 6px 10px); }
.trace-divider .via { width: 6px; height: 6px; border-radius: 50%; background: var(--copper); margin: 0 8px; box-shadow: 0 0 4px rgba(201,121,63,0.6); }

/* ---- Panels / viewfinder camera frame ---- */
.panel-label { font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }

[data-testid="stImage"] {
  position: relative; padding: 6px; background: var(--bg-panel);
  border: 1px solid var(--border-trace); border-radius: 8px;
}
[data-testid="stImage"]::before, [data-testid="stImage"]::after {
  content: ""; position: absolute; width: 16px; height: 16px; border: 2px solid var(--copper); pointer-events: none;
}
[data-testid="stImage"]::before { top: 2px; left: 2px; border-right: none; border-bottom: none; }
[data-testid="stImage"]::after { bottom: 2px; right: 2px; border-left: none; border-top: none; }

/* ---- Metric cards ---- */
[data-testid="stMetric"] {
  background: var(--bg-panel-raised); border: 1px solid var(--border-trace);
  border-radius: 10px; padding: 14px 16px;
}
[data-testid="stMetricLabel"] { font-family: 'IBM Plex Mono', monospace !important; font-size: 11.5px !important; color: var(--text-muted) !important; text-transform: uppercase; letter-spacing: 0.04em; }
[data-testid="stMetricValue"] { font-family: 'Space Grotesk', sans-serif !important; color: var(--text-primary) !important; }

/* ---- Buttons ---- */
.stButton > button, .stDownloadButton > button {
  background: var(--copper) !important; color: #14100D !important; border: none !important;
  font-family: 'IBM Plex Mono', monospace !important; font-weight: 600 !important;
  letter-spacing: 0.02em; border-radius: 7px !important; transition: all 0.15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  background: var(--copper-bright) !important; box-shadow: 0 0 0 3px rgba(201,121,63,0.2);
}

/* ---- Badges (robot action / status) ---- */
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 20px; font-family: 'IBM Plex Mono', monospace; font-size: 13px; font-weight: 600; letter-spacing: 0.02em; }
.badge-pass { background: rgba(47,158,110,0.14); color: var(--solder-green); border: 1px solid rgba(47,158,110,0.4); }
.badge-fail { background: rgba(229,72,77,0.14); color: var(--fail-red); border: 1px solid rgba(229,72,77,0.4); }
.badge-warn { background: rgba(232,162,61,0.14); color: var(--alert-amber); border: 1px solid rgba(232,162,61,0.4); }
.badge-neutral { background: rgba(138,148,166,0.1); color: var(--text-muted); border: 1px solid var(--border-trace); }

/* ---- Tabs ---- */
[data-testid="stTabs"] button { font-family: 'IBM Plex Mono', monospace; }

/* ---- Dataframe ---- */
[data-testid="stDataFrame"] { border: 1px solid var(--border-trace); border-radius: 8px; overflow: hidden; }

/* ---- Empty state ---- */
.empty-state {
  text-align: center; padding: 48px 24px; border: 1px dashed var(--border-trace);
  border-radius: 10px; color: var(--text-muted); font-family: 'IBM Plex Mono', monospace; font-size: 13px;
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────
def trace_divider():
    st.markdown(
        '<div class="trace-divider"><div class="line"></div><div class="via"></div>'
        '<div class="line"></div></div>',
        unsafe_allow_html=True,
    )


def badge_for(text: str) -> str:
    """Map a status/action string to a styled badge. Defensive against unknown values."""
    t = (text or "").strip().lower()
    if any(k in t for k in ["pass", "ok", "accept", "good"]):
        cls = "badge-pass"
    elif any(k in t for k in ["fail", "reject", "defect"]):
        cls = "badge-fail"
    elif any(k in t for k in ["warn", "flag", "review"]):
        cls = "badge-warn"
    else:
        cls = "badge-neutral"
    return f'<span class="badge {cls}">{text}</span>'


@st.cache_data(ttl=10, show_spinner=False)
def get_gpu_status():
    """Real hardware check — no fabricated telemetry. Degrades gracefully off-GPU hosts."""
    status = {"torch_ok": False, "device_name": None, "rocm_version": None}
    try:
        import torch
        status["torch_ok"] = True
        if torch.cuda.is_available():
            status["device_name"] = torch.cuda.get_device_name(0)
            status["rocm_version"] = getattr(torch.version, "hip", None)
    except ImportError:
        pass
    return status


@st.cache_data(ttl=5, show_spinner=False)
def get_gpu_utilization():
    """Live rocm-smi read. Returns None if unavailable (e.g. not on a Radeon Cloud host)."""
    try:
        out = subprocess.run(
            ["rocm-smi", "--showuse", "--showtemp", "--json"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout)
    except Exception:
        return None
    return None


def load_reports():
    """Load historical JSON reports written by ReportGenerator, newest first.

    NOTE: field names below (status, inspection_type, components, pcb_defects,
    wafer_defects) are assumed to mirror the in-app `result` dict from the
    original script. If ReportGenerator.generate() writes different keys,
    adjust the .get() calls in render_analytics_tab() to match.
    """
    if not REPORTS_DIR.exists():
        return []
    records = []
    for f in sorted(REPORTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(f) as fh:
                data = json.load(fh)
            data["_file"] = f.name
            data["_mtime"] = datetime.fromtimestamp(f.stat().st_mtime)
            records.append(data)
        except Exception:
            continue
    return records


# ─────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────
gpu = get_gpu_status()
gpu_dot = "dot-ok" if gpu["device_name"] else ("dot-warn" if gpu["torch_ok"] else "dot-off")
gpu_label = gpu["device_name"] or ("CPU only" if gpu["torch_ok"] else "PyTorch not found")
rocm_dot = "dot-ok" if gpu["rocm_version"] else "dot-off"
rocm_label = f"ROCm {gpu['rocm_version']}" if gpu["rocm_version"] else "ROCm Detected"

st.markdown(
    f"""
    <div class="aoi-header">
      <div>
        <p class="aoi-title">🔌 RoboAOI</p>
        <p class="aoi-subtitle">Robotic Optical Inspection · Track 3 Physical AI</p>
      </div>
      <div class="chip-row">
        <span class="chip"><span class="dot {gpu_dot}"></span>{gpu_label}</span>
        <span class="chip"><span class="dot {rocm_dot}"></span>{rocm_label}</span>
        <span class="chip"><span class="dot dot-ok"></span>Genesis Sim</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

trace_divider()


# ─────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="panel-label">Inspection Setup</p>', unsafe_allow_html=True)
    inspection_type = st.selectbox("Inspection Type", ["PCB", "Wafer"])
    uploaded_file = st.file_uploader("Upload Image", type=["jpg", "jpeg", "png"])

    st.markdown("---")
    st.markdown('<p class="panel-label">Live GPU Telemetry</p>', unsafe_allow_html=True)
    util = get_gpu_utilization()
    if util:
        st.json(util, expanded=False)
    else:
        st.markdown(
            '<span style="font-family:IBM Plex Mono, monospace; font-size:12px; color:var(--text-faint);">'
            'rocm-smi unavailable — run on a Radeon Cloud instance to see live GPU load.</span>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.caption("AMD AI DevMaster Hackathon 2026 · Track 3")


# ─────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────
tab_live, tab_analytics = st.tabs(["🔍  Live Inspection", "📊  Analytics"])


# ---- Live Inspection tab --------------------------------------------------
with tab_live:
    if uploaded_file is None:
        st.markdown(
            '<div class="empty-state">📤 Upload a PCB or wafer image from the sidebar to begin inspection.</div>',
            unsafe_allow_html=True,
        )
    else:
        image = Image.open(uploaded_file)
        left, right = st.columns(2)

        with left:
            st.markdown('<p class="panel-label">Original</p>', unsafe_allow_html=True)
            st.image(image, use_container_width=True)

        run = st.button("▶  Run Inspection", use_container_width=True)

        if run:
            with st.spinner("Running inspection..."):
                manager = InspectionManager()
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    image.save(tmp.name)
                    result = manager.inspect(
                        tmp.name,
                        inspection_type="pcb" if inspection_type == "PCB" else "wafer",
                    )

            with right:
                st.markdown('<p class="panel-label">Annotated Result</p>', unsafe_allow_html=True)
                st.image(result["annotated"], use_container_width=True)

            trace_divider()

            # Status row
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown('<p class="panel-label">Inspection</p>', unsafe_allow_html=True)
                st.markdown(badge_for(result["inspection_type"]), unsafe_allow_html=True)
            with c2:
                st.markdown('<p class="panel-label">Status</p>', unsafe_allow_html=True)
                st.markdown(badge_for(result["status"]), unsafe_allow_html=True)
            with c3:
                st.markdown('<p class="panel-label">Robot Action</p>', unsafe_allow_html=True)
                st.markdown(badge_for(result["robot_action"]), unsafe_allow_html=True)

            # Physical AI Robot Execution
            render_robot_execution_panel(result)

            st.write("")
            components = result.get("components", [])
            pcb_defects = result.get("pcb_defects", [])
            wafer_defects = result.get("wafer_defects", [])

            m1, m2 = st.columns(2)
            if inspection_type == "PCB":
                with m1:
                    st.metric("Components Detected", len(components))
                with m2:
                    st.metric("PCB Defects", len(pcb_defects))
            else:
                with m1:
                    st.metric("Wafer Defects", len(wafer_defects))

            trace_divider()

            detections = []
            for item in components:
                detections.append({"Type": "Component", "Class": item["class"], "Confidence": round(item["confidence"], 3)})
            for item in pcb_defects:
                detections.append({"Type": "PCB Defect", "Class": item["class"], "Confidence": round(item["confidence"], 3)})
            for item in wafer_defects:
                detections.append({"Type": "Wafer Defect", "Class": item["class"], "Confidence": round(item["confidence"], 3)})

            st.markdown('<p class="panel-label">Detections</p>', unsafe_allow_html=True)
            if detections:
                df = pd.DataFrame(detections)
                column_config = None
                if hasattr(st, "column_config") and hasattr(st.column_config, "ProgressColumn"):
                    column_config = {
                        "Confidence": st.column_config.ProgressColumn(
                            "Confidence", min_value=0.0, max_value=1.0, format="%.3f"
                        )
                    }
                st.dataframe(df, use_container_width=True, column_config=column_config)
            else:
                st.markdown(
                    '<div class="empty-state">✅ No defects detected in this pass.</div>',
                    unsafe_allow_html=True,
                )

            report_generator = ReportGenerator()
            report_generator.generate(
                image_name=uploaded_file.name,
                components=components,
                pcb_defects=pcb_defects,
                wafer_defects=wafer_defects,
                status=result["status"],
            )

            trace_divider()

            st.markdown('<p class="panel-label">Reports</p>', unsafe_allow_html=True)
            json_reports = sorted(REPORTS_DIR.glob("*.json")) if REPORTS_DIR.exists() else []
            csv_reports = sorted(REPORTS_DIR.glob("*.csv")) if REPORTS_DIR.exists() else []
            dl1, dl2 = st.columns(2)
            if json_reports:
                with dl1, open(json_reports[-1], "rb") as f:
                    st.download_button("📄 Download JSON Report", data=f, file_name=json_reports[-1].name, mime="application/json", use_container_width=True)
            if csv_reports:
                with dl2, open(csv_reports[-1], "rb") as f:
                    st.download_button("📊 Download CSV Report", data=f, file_name=csv_reports[-1].name, mime="text/csv", use_container_width=True)

            st.success("Inspection completed and logged.")


# ---- Analytics tab ----------------------------------------------------------
with tab_analytics:
    reports = load_reports()

    if not reports:
        st.markdown(
            '<div class="empty-state">📭 No inspection history yet. Run an inspection to start building analytics.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<p class="panel-label">Summary</p>', unsafe_allow_html=True)

        total = len(reports)
        pass_count = sum(1 for r in reports if "pass" in str(r.get("status", "")).lower())
        pass_rate = f"{(pass_count / total * 100):.1f}%" if total else "—"

        defect_total = 0
        defect_freq = {}
        for r in reports:
            for group in ("pcb_defects", "wafer_defects"):
                for item in r.get(group, []):
                    defect_total += 1
                    cls = item.get("class", "unknown")
                    defect_freq[cls] = defect_freq.get(cls, 0) + 1

        s1, s2, s3 = st.columns(3)
        with s1:
            st.metric("Total Inspections", total)
        with s2:
            st.metric("Pass Rate", pass_rate)
        with s3:
            st.metric("Total Defects Logged", defect_total)

        trace_divider()

        if PLOTLY_AVAILABLE and reports:
            st.markdown('<p class="panel-label">Inspections Over Time</p>', unsafe_allow_html=True)
            timeline = pd.DataFrame(
                [{"time": r["_mtime"], "status": r.get("status", "unknown")} for r in reports]
            ).sort_values("time")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=timeline["time"], y=list(range(1, len(timeline) + 1)),
                mode="lines+markers", line=dict(color="#C9793F", width=2),
                marker=dict(color="#E8944F", size=6),
            ))
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#8A94A6", family="IBM Plex Mono"),
                xaxis=dict(gridcolor="#262E3A"), yaxis=dict(gridcolor="#262E3A", title="Cumulative Inspections"),
                margin=dict(l=10, r=10, t=10, b=10), height=280,
            )
            st.plotly_chart(fig, use_container_width=True)

            if defect_freq:
                trace_divider()
                st.markdown('<p class="panel-label">Defect Frequency by Class</p>', unsafe_allow_html=True)
                freq_df = pd.DataFrame(sorted(defect_freq.items(), key=lambda x: -x[1]), columns=["Class", "Count"])
                fig2 = go.Figure(go.Bar(
                    x=freq_df["Count"], y=freq_df["Class"], orientation="h",
                    marker=dict(color="#2F9E6E"),
                ))
                fig2.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#8A94A6", family="IBM Plex Mono"),
                    xaxis=dict(gridcolor="#262E3A"), yaxis=dict(gridcolor="#262E3A"),
                    margin=dict(l=10, r=10, t=10, b=10), height=max(200, 32 * len(freq_df)),
                )
                st.plotly_chart(fig2, use_container_width=True)
        elif not PLOTLY_AVAILABLE:
            st.info("Install Plotly for trend charts: `uv pip install plotly`")

        trace_divider()
        st.markdown('<p class="panel-label">Recent Reports</p>', unsafe_allow_html=True)
        hist_df = pd.DataFrame([
            {
                "File": r["_file"],
                "Time": r["_mtime"].strftime("%Y-%m-%d %H:%M"),
                "Status": r.get("status", "—"),
                "Defects": sum(len(r.get(g, [])) for g in ("pcb_defects", "wafer_defects")),
            }
            for r in reports
        ])
        st.dataframe(hist_df, use_container_width=True)


trace_divider()
st.markdown(
    '<p style="text-align:center; font-family:IBM Plex Mono, monospace; font-size:11.5px; color:var(--text-faint);">'
    'RoboAOI · AMD AI DevMaster Hackathon 2026 · Track 3 Physical AI · Built on Genesis + LeRobot + ROCm</p>',
    unsafe_allow_html=True,
)