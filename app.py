from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from core import (
    FileMatch,
    LocalEmbeddingClient,
    LocalCrossEncoderReranker,
    LocalOllama,
    LocalRetriever,
    LocalVLLM,
    assess_file_matches,
    compile_intent,
    is_file_inventory_request,
    local_runtime_status,
    markdown_brief,
    route_workspace_request,
    redact_sensitive_text,
    run_court,
    scan_workspace,
    summarize_artifact,
)


ROOT = Path(__file__).parent
DEMO_DIR = ROOT / "demo_corpus"
UPLOAD_DIR = ROOT / "data" / "uploads"
EXPORT_DIR = ROOT / "data" / "exports"
INDEX_FILE = ROOT / "data" / "workspace_index.json"

st.set_page_config(page_title="ClaimCourt", page_icon="⚖", layout="wide")

UI_TEXT = {
    "zh": {
        "language": "语言 / LANGUAGE",
        "chinese": "中文",
        "english": "English",
        "tagline": "私有本地证据法庭 // 模糊记忆编译器",
        "privacy_warning": "私有部署警告：真实资料已索引时，不要将此界面暴露到公网。",
        "local_inference": "本地推理",
        "runtime": "运行时",
        "runtime_endpoint": "本地模型端点",
        "local_model": "本地模型",
        "use_gpu": "使用本地 GPU 推理",
        "intent_compiler": "使用本地模糊意图编译器",
        "intent_help": "把不完整记忆编译成主题、关系、时间和检索扩展。",
        "intent_endpoint": "意图编译器端点",
        "intent_model": "意图编译器模型",
        "intent_model_help": "已部署 ClaimCourt LoRA 时填写适配器模型，否则使用本地 Qwen 基线。",
        "championship": "冠军模式（禁止回退）",
        "championship_help": "开启后，本地法官不可用会直接报错，不会生成模拟裁决。",
        "local_only": "不调用外部模型服务。选中的运行时必须运行在当前 Radeon Cloud 实例。",
        "check_runtime": "检查本地运行时",
        "semantic": "语义检索",
        "embeddings": "使用本地语义向量",
        "embedding_runtime": "向量运行时",
        "embedding_endpoint": "向量端点",
        "embedding_model": "向量模型",
        "embedding_optional": "向量检索是可选增强；端点不可用时继续使用确定性混合检索。",
        "reranker": "使用本地 Cross-Encoder 重排",
        "reranker_path": "Cross-Encoder 模型路径",
        "reranker_help": "只加载本地缓存或私有目录中的模型，不调用远程 API。",
        "reranker_lazy": "重排模型将在第一次查询时加载；依赖缺失时保留混合检索。",
        "fts_active": "SQLite FTS5 词法索引已激活",
        "fts_persisted": "，并已与证据账本一起持久化",
        "fts_memory": "（内存模式）",
        "fts_unavailable": "FTS5 不可用，使用内存词法检索",
        "intake": "证据接入",
        "workspace": "本地工作区目录",
        "upload": "添加私有文档",
        "load_demo": "加载稳定演示案件",
        "index_uploads": "索引选中文档",
        "index_workspace": "索引本地工作区",
        "scan_result": "目录扫描结果",
        "scan_entries": "扫描条目",
        "scan_files": "可索引文件",
        "scan_skipped": "跳过条目",
        "scan_skip_reasons": "跳过原因",
        "scan_limit": "已达到目录扫描文件数量上限，请缩小目录范围。",
        "scan_truncated": "条跳过诊断因数量上限未显示。",
        "scan_sensitive": "扫描索引中的敏感记录",
        "request": "私有工作区请求",
        "default_claim": "供应商是否在合同中承诺了 99.9% 的可用性？",
        "privacy_boundary": "隐私边界",
        "privacy_copy": "检索、Agent 调用、记忆和导出都在本地运行。写入报告前需要明确批准。",
        "indexed_chunks": "已索引分块",
        "query_memory": "查询记忆",
        "semantic_configured": "语义向量已配置，将在下次索引时激活。",
        "ocr_chunks": "OCR 分块",
        "persistent_history": "持久历史",
        "run_request": "运行私有工作区请求",
        "intent_plan": "模糊意图计划",
        "compiler": "编译器",
        "route": "路由",
        "confidence": "置信度",
        "topics": "主题",
        "relations": "关系",
        "memory_signals": "记忆信号",
        "expanded_terms": "扩展词",
        "search_scope": "搜索范围",
        "clarification": "需要澄清",
        "local_matches": "本地文件候选",
        "why_match": "匹配原因",
        "summary": "本地文件摘要",
        "read_from": "读取来源",
        "chunks_read": "读取分块",
        "local_passes": "本地推理轮次",
        "end_to_end": "端到端",
        "output_tokens": "输出 token",
        "evidence_packet": "已检索证据包",
        "evidence_packet_copy": "即使本地模型或结构化法官失败，这些证据仍会保留。",
        "court_record": "法庭记录",
        "verdict": "裁决",
        "inference": "推理",
        "first_token": "首 token",
        "tokens_per_second": "tokens/s",
        "prosecution": "检方",
        "defense": "辩方",
        "cited_evidence": "已引用证据",
        "ledger": "证据账本",
        "timeline": "矛盾时间线",
        "missing": "缺失证据",
        "next_action": "建议下一步",
        "approve_export": "我批准将这份决策简报写入本地文件。",
        "download": "下载已批准简报",
        "version_history": "工作区版本历史",
        "diagnostics": "查看接入诊断",
        "model_warning": "本地意图模型不可用，已保留确定性计划",
    },
    "en": {
        "language": "LANGUAGE / 语言",
        "chinese": "中文",
        "english": "English",
        "tagline": "PRIVATE LOCAL EVIDENCE COURT // FUZZY MEMORY COMPILER",
        "privacy_warning": "PRIVATE DEPLOYMENT: never expose this UI publicly while real evidence is indexed.",
        "local_inference": "LOCAL INFERENCE",
        "runtime": "Runtime",
        "runtime_endpoint": "Local model endpoint",
        "local_model": "Local model",
        "use_gpu": "Use local GPU inference",
        "intent_compiler": "Use local fuzzy-intent compiler",
        "intent_help": "Compile incomplete recollections into topics, relations, time hints, and search expansions.",
        "intent_endpoint": "Intent compiler endpoint",
        "intent_model": "Intent compiler model",
        "intent_model_help": "Use the ClaimCourt LoRA adapter when served, or the same local Qwen baseline.",
        "championship": "Championship mode (no fallback)",
        "championship_help": "A missing local judge becomes an error instead of a simulated verdict.",
        "local_only": "No external model provider is contacted. The selected runtime must run on this Radeon Cloud instance.",
        "check_runtime": "Check local runtime",
        "semantic": "SEMANTIC RETRIEVAL",
        "embeddings": "Use local semantic embeddings",
        "embedding_runtime": "Embedding runtime",
        "embedding_endpoint": "Embedding endpoint",
        "embedding_model": "Embedding model",
        "embedding_optional": "Embeddings are optional; deterministic hybrid retrieval remains active if unavailable.",
        "reranker": "Use local Cross-Encoder reranker",
        "reranker_path": "Cross-Encoder model path",
        "reranker_help": "Load only from a local cache or private directory. No remote API is used.",
        "reranker_lazy": "Lazy-loaded on the first query; missing dependencies retain hybrid retrieval.",
        "fts_active": "SQLite FTS5 lexical index active",
        "fts_persisted": ", persisted beside the evidence ledger",
        "fts_memory": " (memory mode)",
        "fts_unavailable": "FTS5 unavailable; using in-memory lexical retrieval",
        "intake": "EVIDENCE INTAKE",
        "workspace": "Local workspace folder",
        "upload": "Add private documents",
        "load_demo": "Load stable demo case",
        "index_uploads": "Index selected documents",
        "index_workspace": "Index local workspace",
        "scan_result": "WORKSPACE SCAN RESULT",
        "scan_entries": "Entries scanned",
        "scan_files": "Indexable files",
        "scan_skipped": "Skipped entries",
        "scan_skip_reasons": "Skip reason",
        "scan_limit": "The workspace file limit was reached; select a narrower root.",
        "scan_truncated": "skip diagnostics were omitted by the display limit.",
        "scan_sensitive": "Scan indexed files for sensitive records",
        "request": "PRIVATE WORKSPACE REQUEST",
        "default_claim": "Did the vendor contractually commit to 99.9% uptime?",
        "privacy_boundary": "PRIVACY BOUNDARY",
        "privacy_copy": "Retrieval, agent calls, memory, and export run locally. Export requires explicit approval.",
        "indexed_chunks": "Indexed chunks",
        "query_memory": "Query memory",
        "semantic_configured": "Semantic embeddings configured; they will activate on the next index.",
        "ocr_chunks": "OCR chunks",
        "persistent_history": "Persistent history",
        "run_request": "RUN PRIVATE WORKSPACE REQUEST",
        "intent_plan": "FUZZY INTENT PLAN",
        "compiler": "Compiler",
        "route": "Route",
        "confidence": "Confidence",
        "topics": "Topics",
        "relations": "Relations",
        "memory_signals": "Memory signals",
        "expanded_terms": "Expanded terms",
        "search_scope": "Search scope",
        "clarification": "Needs clarification",
        "local_matches": "LOCAL FILE MATCHES",
        "why_match": "WHY THIS MATCHED",
        "summary": "LOCAL ARTIFACT SUMMARY",
        "read_from": "Read from",
        "chunks_read": "Chunks read",
        "local_passes": "Local passes",
        "end_to_end": "End to end",
        "output_tokens": "Output tokens",
        "evidence_packet": "RETRIEVED EVIDENCE PACKET",
        "evidence_packet_copy": "This packet remains visible even if the local model or structured judge fails.",
        "court_record": "COURT RECORD",
        "verdict": "Verdict",
        "inference": "Inference",
        "first_token": "First token",
        "tokens_per_second": "Tokens/s",
        "prosecution": "PROSECUTION",
        "defense": "DEFENSE",
        "cited_evidence": "CITED EVIDENCE",
        "ledger": "EVIDENCE LEDGER",
        "timeline": "CONTRADICTION TIMELINE",
        "missing": "MISSING EVIDENCE",
        "next_action": "RECOMMENDED NEXT ACTION",
        "approve_export": "I approve writing this decision brief to a local file.",
        "download": "Download approved brief",
        "version_history": "WORKSPACE VERSION HISTORY",
        "diagnostics": "Inspect ingestion diagnostics",
        "model_warning": "Local intent model unavailable; deterministic plan retained",
    },
}

if "language" not in st.session_state:
    st.session_state.language = "zh"
language = st.session_state.language


def tr(key: str) -> str:
    return UI_TEXT[language].get(key, key)


st.markdown(
    """
    <style>
    :root { --cc-bg:#070a0f; --cc-panel:#0c1219; --cc-border:#1b3540; --cc-green:#72f1b8; --cc-cyan:#5ee7f7; --cc-amber:#ffcf70; --cc-muted:#81919c; }
    .stApp { background:var(--cc-bg); color:#d9e5e9; }
    header[data-testid="stHeader"] { background:var(--cc-bg) !important; border-bottom:1px solid #101d25; }
    [data-testid="stToolbar"] { display:none; }
    [data-testid="stSidebarCollapsedControl"] button, [data-testid="stSidebarCollapseButton"] button { color:var(--cc-cyan) !important; }
    [data-testid="stSidebar"] { background:#080d13; border-right:1px solid var(--cc-border); }
    [data-testid="stSidebar"] > div:first-child { padding-top:1.2rem; }
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
    [data-testid="stSidebar"] label p,
    [data-testid="stSidebar"] label span { color:#8fa4ae !important; }
    h1, h2, h3, h4 { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace !important; letter-spacing:.04em; }
    h1 { color:var(--cc-green); text-transform:uppercase; font-size:2.5rem !important; text-shadow:0 0 18px rgba(114,241,184,.25); }
    h2, h3, h4 { color:var(--cc-cyan); }
    [data-testid="stCaptionContainer"], .stCaption { color:var(--cc-muted); }
    [data-testid="stAlert"] { background:#0d171d; border:1px solid var(--cc-border); }
    [data-testid="stMetric"] { background:var(--cc-panel); border:1px solid var(--cc-border); padding:.8rem; }
    [data-testid="stMetricLabel"] { color:var(--cc-muted); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; text-transform:uppercase; font-size:.72rem; }
    [data-testid="stMetricValue"] { color:var(--cc-green); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
    .stButton > button, .stDownloadButton > button { background:#0b171b; color:var(--cc-green); border:1px solid #2c7c70; border-radius:2px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; text-transform:uppercase; }
    .stButton > button:hover, .stDownloadButton > button:hover { color:#06100d; background:var(--cc-green); border-color:var(--cc-green); }
    textarea, input { background:#080d12 !important; color:#d9e5e9 !important; border-color:var(--cc-border) !important; font-family:ui-monospace,SFMono-Regular,Menlo,monospace !important; }
    [data-testid="stExpander"] { background:var(--cc-panel); border:1px solid var(--cc-border); border-radius:2px; }
    code, pre { color:var(--cc-green) !important; background:#05080b !important; }
    .cc-kicker { color:var(--cc-cyan); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.72rem; letter-spacing:.16em; margin-bottom:.4rem; }
    .cc-status { border:1px solid var(--cc-border); background:var(--cc-panel); padding:.7rem .9rem; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--cc-muted); }
    .cc-status strong { color:var(--cc-green); }
    </style>
    """,
    unsafe_allow_html=True,
)

SESSION_DEFAULTS = {
    "retriever": lambda: LocalRetriever(INDEX_FILE),
    "case": lambda: None,
    "runtime_status": lambda: None,
    "sensitive_findings": list,
    "file_matches": list,
    "retrieval_decision": lambda: None,
    "intent_plan": lambda: None,
    "intent_telemetry": lambda: None,
    "intent_mode": lambda: "deterministic",
    "retrieved_preview": list,
    "artifact_summary": lambda: None,
    "artifact_summary_telemetry": lambda: None,
    "request_error": lambda: "",
    "demo_mode": lambda: False,
    "workspace_scan": lambda: None,
}
for state_key, factory in SESSION_DEFAULTS.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = factory()


def reset_result_state() -> None:
    st.session_state.case = None
    st.session_state.sensitive_findings = []
    st.session_state.file_matches = []
    st.session_state.retrieval_decision = None
    st.session_state.intent_plan = None
    st.session_state.intent_telemetry = None
    st.session_state.intent_mode = "deterministic"
    st.session_state.retrieved_preview = []
    st.session_state.artifact_summary = None
    st.session_state.artifact_summary_telemetry = None
    st.session_state.request_error = ""


def index_demo() -> None:
    embedder = st.session_state.retriever.embedder
    st.session_state.retriever = LocalRetriever(INDEX_FILE, embedder=embedder)
    count = st.session_state.retriever.index_paths(DEMO_DIR.glob("*"))
    st.session_state.indexed_count = count
    reset_result_state()
    st.session_state.demo_mode = True
    st.session_state.workspace_scan = None


st.title("ClaimCourt")
st.markdown('<div class="cc-kicker">[ LOCAL // ROCM // PRIVATE // FUZZY-INTENT ]</div>', unsafe_allow_html=True)
st.caption(tr("tagline"))
st.warning(tr("privacy_warning"))

with st.sidebar:
    st.radio(
        tr("language"),
        ["zh", "en"],
        format_func=lambda code: UI_TEXT[code]["chinese"] if code == "zh" else UI_TEXT[code]["english"],
        key="language",
        horizontal=True,
    )
    language = st.session_state.language
    st.markdown('<div class="cc-kicker">CLAIMCOURT // CONTROL DECK</div>', unsafe_allow_html=True)
    st.subheader(tr("local_inference"))
    # The competition path is the verified Radeon Cloud vLLM service; Ollama
    # remains available as an explicit compatibility option.
    runtime = st.selectbox(tr("runtime"), ["vLLM ROCm", "Ollama ROCm"], key="runtime")
    default_endpoint = "http://localhost:11434" if runtime == "Ollama ROCm" else "http://localhost:8000/v1"
    default_model = "qwen3:32b-q8_0" if runtime == "Ollama ROCm" else "Qwen3-8B"
    endpoint = st.text_input(tr("runtime_endpoint"), default_endpoint, key="endpoint")
    model = st.text_input(tr("local_model"), default_model, key="model")
    use_local_inference = st.toggle(tr("use_gpu"), value=True, key="use_local_inference")
    use_intent_compiler = st.toggle(
        tr("intent_compiler"),
        value=True,
        help=tr("intent_help"),
        key="use_intent_compiler",
    )
    intent_endpoint = st.text_input(
        tr("intent_endpoint"),
        os.getenv("CLAIMCOURT_INTENT_ENDPOINT", endpoint),
        key="intent_endpoint",
    )
    intent_model = st.text_input(
        tr("intent_model"),
        os.getenv("CLAIMCOURT_INTENT_MODEL", model),
        help=tr("intent_model_help"),
        key="intent_model",
    )
    championship_mode = st.toggle(
        tr("championship"),
        value=False,
        help=tr("championship_help"),
        key="championship_mode",
    )
    st.caption(tr("local_only"))
    if st.button(tr("check_runtime"), use_container_width=True, key="check_runtime"):
        st.session_state.runtime_status = local_runtime_status(runtime, endpoint, model)
    status = st.session_state.runtime_status
    if status:
        if status.get("available"):
            st.success(f"{status['service']} | {status['processor']}")
            st.caption(
                f"GPU: {status.get('gpu_name', 'unknown')} · "
                f"Architecture: {status.get('gpu_architecture', 'unknown')} · "
                f"ROCm: {status.get('rocm_version', 'unknown')} · "
                f"HIP: {status.get('hip_version', 'unknown')} · "
                f"vLLM: {status.get('vllm_version', 'unknown')}"
            )
            if status.get("model_loaded"):
                vram_gib = status.get("vram_used_bytes", status.get("size_vram", 0)) / (1024 ** 3)
                total_vram_gib = status.get("vram_total_bytes", 0) / (1024 ** 3)
                context = status.get("context_length", 0)
                vram_label = f"{vram_gib:.1f}/{total_vram_gib:.1f} GiB" if total_vram_gib else f"{vram_gib:.1f} GiB"
                st.caption(
                    f"Model resident locally | VRAM: {vram_label} | Context: {context or 'unknown'} | "
                    f"Dtype: {status.get('dtype', 'unknown')} | Quantization: {status.get('quantization', 'unknown')} | "
                    f"GPU memory target: {status.get('gpu_memory_utilization', 'unknown')}"
                )
            else:
                st.warning("Runtime is reachable, but the selected model is not loaded.")
        else:
            st.error(f"Local runtime unavailable: {status.get('error', 'unknown error')}")
    st.divider()
    st.subheader(tr("semantic"))
    use_embeddings = st.toggle(tr("embeddings"), value=True, key="use_embeddings")
    if use_embeddings:
        embedding_runtime = st.selectbox(tr("embedding_runtime"), ["vLLM ROCm", "Ollama ROCm"], key="embedding_runtime")
        embedding_endpoint = st.text_input(
            tr("embedding_endpoint"),
            os.getenv(
                "CLAIMCOURT_EMBEDDING_ENDPOINT",
                "http://localhost:11434" if embedding_runtime == "Ollama ROCm" else "http://localhost:8001/v1",
            ),
            key="embedding_endpoint",
        )
        embedding_model = st.text_input(
            tr("embedding_model"),
            os.getenv(
                "CLAIMCOURT_EMBEDDING_MODEL",
                "nomic-embed-text" if embedding_runtime == "Ollama ROCm" else "/workspace/models/bge-small-zh-v1.5",
            ),
            key="embedding_model",
        )
        st.session_state.retriever.embedder = LocalEmbeddingClient(
            embedding_runtime,
            embedding_endpoint,
            embedding_model,
        )
        st.caption(tr("embedding_optional"))
    else:
        st.session_state.retriever.embedder = None
        st.session_state.retriever.embedding_model = ""
    use_reranker = st.toggle(tr("reranker"), value=False, key="use_reranker")
    if use_reranker:
        reranker_model = st.text_input(
            tr("reranker_path"),
            os.getenv("CLAIMCOURT_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            help=tr("reranker_help"),
            key="reranker_model",
        )
        if reranker_model.strip():
            st.session_state.retriever.reranker = LocalCrossEncoderReranker(reranker_model.strip())
            st.caption(tr("reranker_lazy"))
    else:
        st.session_state.retriever.reranker = None
        st.session_state.retriever.reranker_model = ""
    if st.session_state.retriever.fts5_active:
        st.caption(
            tr("fts_active") +
            (tr("fts_persisted") if st.session_state.retriever.fts5_durable else tr("fts_memory"))
        )
    elif st.session_state.retriever.fts_error:
        st.warning(f"{tr('fts_unavailable')}: {st.session_state.retriever.fts_error}")
    st.divider()
    st.subheader(tr("intake"))
    workspace = st.text_input(tr("workspace"), placeholder="/workspace/private-case", key="workspace")
    uploads = st.file_uploader(tr("upload"), type=["pdf", "doc", "docx", "pptx", "txt", "md", "eml"], accept_multiple_files=True, key="uploads")
    if st.button(tr("load_demo"), use_container_width=True, key="load_demo"):
        index_demo()
        st.success(f"Indexed {st.session_state.indexed_count} local evidence chunks.")
    if uploads and st.button(tr("index_uploads"), use_container_width=True, key="index_uploads"):
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        saved = []
        for upload in uploads:
            safe_name = Path(upload.name).name
            if not safe_name or safe_name in {".", ".."}:
                st.error(f"Rejected invalid upload name: {upload.name}")
                continue
            destination = UPLOAD_DIR / safe_name
            destination.write_bytes(upload.getbuffer())
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
            saved.append(destination)
        embedder = st.session_state.retriever.embedder
        st.session_state.retriever = LocalRetriever(INDEX_FILE, embedder=embedder)
        st.session_state.indexed_count = st.session_state.retriever.index_paths(saved, accumulate=True)
        reset_result_state()
        st.session_state.demo_mode = False
        st.session_state.workspace_scan = None
        st.success(f"Indexed {st.session_state.indexed_count} local evidence chunks.")
    if st.button(tr("index_workspace"), use_container_width=True, key="index_workspace"):
        try:
            scan = scan_workspace(Path(workspace).expanduser())
            st.session_state.workspace_scan = scan
            embedder = st.session_state.retriever.embedder
            st.session_state.retriever = LocalRetriever(INDEX_FILE, embedder=embedder)
            st.session_state.indexed_count = st.session_state.retriever.index_paths(scan.files, accumulate=True)
            reset_result_state()
            st.session_state.demo_mode = False
            st.success(f"Indexed {len(scan.files)} local files into {st.session_state.indexed_count} evidence chunks.")
        except (OSError, ValueError) as exc:
            st.error(str(exc))
    scan = st.session_state.workspace_scan
    if scan is not None:
        with st.expander(tr("scan_result"), expanded=bool(scan.skip_counts)):
            st.caption(
                f"{tr('scan_entries')}: {scan.scanned_entries} | "
                f"{tr('scan_files')}: {len(scan.files)} | "
                f"{tr('scan_skipped')}: {sum(scan.skip_counts.values())}"
            )
            if scan.skip_counts:
                st.dataframe(
                    [
                        {tr("scan_skip_reasons"): reason, "Count": count}
                        for reason, count in scan.skip_counts.items()
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            if scan.file_limit_reached:
                st.warning(tr("scan_limit"))
            if scan.truncated_diagnostics:
                st.caption(f"{scan.truncated_diagnostics} {tr('scan_truncated')}")
    if st.button(tr("scan_sensitive"), use_container_width=True, disabled=not st.session_state.retriever.evidence, key="scan_sensitive"):
        st.session_state.sensitive_findings = st.session_state.retriever.scan_sensitive_records()
    if st.session_state.retriever.ingestion_errors:
        st.warning(f"Skipped {len(st.session_state.retriever.ingestion_errors)} unreadable file(s); the remaining files were indexed.")
        with st.expander(tr("diagnostics")):
            st.dataframe(st.session_state.retriever.ingestion_errors[-50:], use_container_width=True, hide_index=True)

left, right = st.columns([1.2, 1])
with left:
    claim = st.text_area(
        tr("request"),
        tr("default_claim"),
        height=120,
        key="claim",
    )
with right:
    st.markdown(f"#### {tr('privacy_boundary')}")
    st.write(tr("privacy_copy"))
    st.markdown(
        f'<div class="cc-status">INDEX STATUS // <strong>{len(st.session_state.retriever.evidence)}</strong> {tr("indexed_chunks")}</div>',
        unsafe_allow_html=True,
    )
    ocr_chunks = sum(1 for item in st.session_state.retriever.evidence if item.ocr_used)
    if ocr_chunks:
        st.caption(f"{tr('ocr_chunks')}: {ocr_chunks}")
    if st.session_state.retriever.embedding_model:
        st.caption(f"Semantic embeddings: {st.session_state.retriever.embedding_model}")
    elif st.session_state.retriever.embedder:
        st.caption(tr("semantic_configured"))
    if st.session_state.retriever.history:
        st.caption(f"{tr('persistent_history')}: {len(st.session_state.retriever.history)}")
    if st.session_state.retriever.query_history:
        with st.expander(f"{tr('query_memory')} ({len(st.session_state.retriever.query_history)})"):
            for item in reversed(st.session_state.retriever.query_history[-10:]):
                st.caption(f"{item['query_id']} · {item['created_at']}")
                st.write(item["query"])
                st.caption(
                    f"Intent: {item['intent']['intent']} · results: {len(item['results'])} · "
                    f"FTS5: {'on' if item.get('fts5_active') else 'off'} · "
                    f"Reranker: {item.get('reranker_model') or 'off'}"
                )
                if item.get("reranker_error"):
                    st.warning(f"Reranker unavailable; hybrid scores retained: {item['reranker_error']}")

if st.button(tr("run_request"), type="primary", use_container_width=True, key="run_request"):
    reset_result_state()
    try:
        if use_intent_compiler and use_local_inference:
            if runtime == "Ollama ROCm":
                intent_llm = LocalOllama(intent_endpoint, intent_model)
            else:
                intent_llm = LocalVLLM(intent_endpoint, intent_model)
        else:
            intent_llm = None
        compiled_plan, intent_telemetry, intent_mode = compile_intent(claim, intent_llm)
        st.session_state.intent_plan = compiled_plan
        st.session_state.intent_telemetry = intent_telemetry
        st.session_state.intent_mode = intent_mode
        if compiled_plan.clarification_needed:
            raise ValueError(compiled_plan.clarification_question)
        route = route_workspace_request(claim, compiled_plan)
        if route == "sensitive_record_scan":
            st.session_state.sensitive_findings = st.session_state.retriever.scan_sensitive_records(claim)
            st.success("Completed local redacted sensitive-record scan.")
        elif route == "file_locator":
            st.session_state.file_matches = st.session_state.retriever.locate_files(
                claim,
                limit=32 if is_file_inventory_request(claim) else 8,
                intent_plan=compiled_plan,
            )
            st.session_state.retrieval_decision = assess_file_matches(
                claim,
                compiled_plan,
                st.session_state.file_matches,
            )
            st.session_state.intent_plan = st.session_state.retriever.last_intent
            if st.session_state.file_matches and st.session_state.retrieval_decision.status == "confident":
                top_match = st.session_state.file_matches[0]
                all_file_evidence = [
                    item for item in st.session_state.retriever.evidence
                    if item.source_path == top_match.source_path
                ]
                if runtime == "Ollama ROCm":
                    llm = LocalOllama(endpoint, model) if use_local_inference else None
                else:
                    llm = LocalVLLM(endpoint, model) if use_local_inference else None
                summary, summary_telemetry = summarize_artifact(claim, top_match, all_file_evidence, llm)
                st.session_state.artifact_summary = summary
                st.session_state.artifact_summary_telemetry = summary_telemetry
            elif st.session_state.retrieval_decision.status in {"ambiguous", "no_match"}:
                st.session_state.request_error = st.session_state.retrieval_decision.clarification_question
            st.success("Completed local file-location search.")
        else:
            retrieved = st.session_state.retriever.search(claim, intent_plan=compiled_plan)
            st.session_state.retrieved_preview = retrieved
            if runtime == "Ollama ROCm":
                llm = LocalOllama(endpoint, model) if use_local_inference else None
            else:
                llm = LocalVLLM(endpoint, model) if use_local_inference else None
            prosecution, defense, verdict, telemetry, mode = run_court(
                claim,
                retrieved,
                llm,
                allow_fallback=st.session_state.demo_mode and not championship_mode,
                demo_mode=st.session_state.demo_mode,
            )
            st.session_state.case = {"retrieved": retrieved, "prosecution": prosecution, "defense": defense, "verdict": verdict, "telemetry": telemetry, "mode": mode}
    except (ValueError, RuntimeError) as exc:
        st.session_state.request_error = str(exc)

if st.session_state.request_error:
    st.error(st.session_state.request_error)

findings = st.session_state.sensitive_findings
if findings:
    st.warning(f"{len(findings)} sensitive record(s) located locally. Values are never displayed or exported by this view.")
    st.dataframe(
        [
            {
                "Source": item.source,
                "Path": item.source_path,
                "Location": item.locator,
                "Type": item.kind,
                "Fingerprint": item.fingerprint,
                "Preview": item.redacted_preview,
                "Score": item.score,
                "Why": ", ".join(item.match_reasons) or "all sensitive records requested",
            }
            for item in findings
        ],
        use_container_width=True,
        hide_index=True,
    )

if st.session_state.retriever.history:
    with st.expander(tr("version_history")):
        st.caption("A changed source is recorded by hash and re-indexed as a new current version.")
        st.dataframe(st.session_state.retriever.history[-20:], use_container_width=True, hide_index=True)
        archived = st.session_state.retriever.archived_versions()
        if archived:
            st.caption(f"Archived prior evidence versions: {len(archived)} excerpt(s)")
            st.dataframe(
                [
                    {
                        "Source": item.source,
                        "Location": item.locator,
                        "Previous SHA-256": item.source_sha256[:16],
                        "Previous excerpt": redact_sensitive_text(item.text[:180]),
                    }
                    for item in archived[-20:]
                ],
                use_container_width=True,
                hide_index=True,
            )

matches = st.session_state.file_matches
plan = st.session_state.intent_plan
if plan:
    st.subheader(tr("intent_plan"))
    st.caption(
        f"{tr('compiler')}: **{plan.compiler}** · {tr('route')}: **{plan.intent}** · {tr('confidence')}: {plan.confidence:.0%}"
    )
    with st.expander(f"[ JSON ] {tr('intent_plan')}", expanded=False):
        st.json({
            "artifact_types": list(plan.artifact_types),
            tr("topics"): list(plan.topics),
            "entities": list(plan.entities),
            "time_hints": list(plan.time_hints),
            tr("relations"): list(plan.relations),
            tr("memory_signals"): list(plan.memory_signals),
            tr("expanded_terms"): list(plan.expanded_terms),
            tr("search_scope"): list(plan.search_scope),
            tr("clarification"): plan.clarification_needed,
            "clarification_question": plan.clarification_question,
        })
    intent_telemetry = st.session_state.intent_telemetry or {}
    if intent_telemetry.get("error"):
        st.warning(f"{tr('model_warning')}: {intent_telemetry['error']}")
    elif st.session_state.intent_mode != "deterministic":
        compiler_metrics = st.columns(3)
        compiler_metrics[0].metric(tr("compiler"), st.session_state.intent_mode)
        compiler_metrics[1].metric(tr("end_to_end"), f"{intent_telemetry.get('end_to_end_latency_seconds', '-')} s")
        compiler_metrics[2].metric(tr("output_tokens"), intent_telemetry.get("completion_tokens", 0))

if matches:
    st.subheader(tr("local_matches"))
    decision = st.session_state.retrieval_decision
    if decision:
        st.caption(
            f"Decision: {decision.status} · confidence {decision.confidence:.0%} · "
            f"margin {decision.score_margin:.3f} · {decision.reason}"
        )
    for match in matches:
        if isinstance(match, FileMatch):
            with st.container(border=True):
                st.markdown(f"**{match.source}** · confidence {match.confidence:.0%} · score {match.score:.3f}")
                st.code(match.source_path)
                st.caption(f"File family: {match.file_family}")
                st.markdown(f"**{tr('why_match')}**")
                for reason in match.reasons:
                    st.write(f"- {reason}")
                if match.duplicate_paths:
                    st.caption(f"Grouped similar copies/versions: {len(match.duplicate_paths)}")
                for item in match.evidence:
                    with st.expander(f"[{item.citation}] {item.locator}"):
                        st.write(redact_sensitive_text(item.text))
        else:
            st.dataframe(
                [{
                    "Source": item.source,
                    "Location": item.locator,
                    "Relevance": item.score,
                    "Excerpt": redact_sensitive_text(item.text[:220]),
                } for item in matches],
                use_container_width=True,
                hide_index=True,
            )

summary = st.session_state.artifact_summary
if summary:
    st.subheader(tr("summary"))
    st.caption(f"{tr('read_from')}: {summary['source_path']}")
    st.write(summary["overview"])
    for item in summary["key_points"]:
        st.write(f"- {item['point']} [{', '.join(item['citations'])}]")
    summary_telemetry = st.session_state.artifact_summary_telemetry or {}
    summary_metrics = st.columns(4)
    summary_metrics[0].metric(tr("chunks_read"), summary_telemetry.get("chunks_summarized", 0))
    summary_metrics[1].metric(tr("local_passes"), summary_telemetry.get("passes", 0))
    summary_metrics[2].metric(tr("end_to_end"), f"{summary_telemetry.get('end_to_end_latency_seconds', '-')} s")
    summary_metrics[3].metric(tr("output_tokens"), summary_telemetry.get("completion_tokens", 0))
    if summary_telemetry.get("model_quality_failures"):
        with st.expander("Model quality warnings"):
            for failure in summary_telemetry["model_quality_failures"]:
                st.warning(failure)

retrieved_preview = st.session_state.retrieved_preview
if retrieved_preview:
    st.subheader(tr("evidence_packet"))
    st.caption(tr("evidence_packet_copy"))
    for item in retrieved_preview:
        with st.expander(f"[{item.citation}] {item.source} | {item.locator} | relevance {item.score}"):
            st.write(redact_sensitive_text(item.text))

case = st.session_state.case
if case:
    verdict = case["verdict"]
    st.divider()
    st.subheader(tr("court_record"))
    metrics = st.columns(3)
    metrics[0].metric(tr("verdict"), verdict["verdict"].replace("_", " ").title())
    metrics[1].metric(tr("confidence"), f"{float(verdict.get('confidence', 0)):.0%}")
    metrics[2].metric(tr("inference"), case["mode"])
    performance = st.columns(4)
    performance[0].metric(tr("first_token"), f"{case['telemetry'].get('first_token_latency_seconds', '-')} s")
    performance[1].metric(tr("end_to_end"), f"{case['telemetry'].get('end_to_end_latency_seconds', '-')} s")
    performance[2].metric(tr("tokens_per_second"), case["telemetry"].get("tokens_per_second", "-"))
    performance[3].metric(tr("output_tokens"), case["telemetry"].get("completion_tokens", "-"))
    if case["telemetry"].get("model_quality_failures"):
        with st.expander("Model quality warnings"):
            for failure in case["telemetry"]["model_quality_failures"]:
                st.warning(failure)
    st.write(verdict.get("reasoning", ""))

    prosecution_col, defense_col = st.columns(2)
    with prosecution_col:
        st.markdown(f"#### {tr('prosecution')}")
        st.write(case["prosecution"].get("position", ""))
        st.caption("Citations: " + ", ".join(case["prosecution"].get("citations", [])))
    with defense_col:
        st.markdown(f"#### {tr('defense')}")
        st.write(case["defense"].get("position", ""))
        st.caption("Citations: " + ", ".join(case["defense"].get("citations", [])))

    st.markdown(f"#### {tr('cited_evidence')}")
    by_citation = {item.citation: item for item in case["retrieved"]}
    for citation in verdict.get("evidence_citations", []):
        item = by_citation.get(citation)
        if item:
            with st.expander(f"[{item.citation}] {item.source} | relevance {item.score}"):
                st.write(redact_sensitive_text(item.text))

    st.markdown(f"#### {tr('ledger')}")
    st.caption("Each source and displayed excerpt is hashed locally so a reviewer can verify the record used for this verdict.")
    st.dataframe(
        [
            {
                "Citation": item.citation,
                "Source": item.source,
                "Location": item.locator,
                "Source SHA-256": item.source_sha256[:16],
                "Excerpt SHA-256": item.evidence_sha256[:16],
            }
            for item in case["retrieved"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    timeline = verdict.get("timeline_events", [])
    if timeline:
        st.markdown(f"#### {tr('timeline')}")
        for event in timeline:
            st.write(f"**{event.get('date', 'Undated')}**  [{event.get('citation', '')}] {event.get('event', '')}")
    st.markdown(f"#### {tr('missing')}")
    for item in verdict.get("missing_evidence", []):
        st.write(f"- {item}")
    st.markdown(f"#### {tr('next_action')}")
    st.info(verdict.get("recommended_next_action", ""))

    st.divider()
    approved = st.checkbox(tr("approve_export"), key="approve_export")
    if approved:
        brief = markdown_brief(verdict, case["retrieved"])
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        export_path = EXPORT_DIR / "claimcourt-decision-brief.md"
        export_path.write_text(brief, encoding="utf-8")
        try:
            os.chmod(EXPORT_DIR, 0o700)
            os.chmod(export_path, 0o600)
        except OSError:
            pass
        st.success(f"Local brief written to {export_path}")
        st.download_button(tr("download"), brief, file_name=export_path.name, mime="text/markdown")
