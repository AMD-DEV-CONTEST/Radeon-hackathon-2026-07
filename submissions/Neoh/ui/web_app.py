# ---- ROCm 环境变量（必须在所有其他 import 之前设置）----
# W7900 / RX 7900 系列是 gfx1100，vLLM 需要 override 才能识别
import os
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "11.0.0")
os.environ.setdefault("PYTORCH_ROCM_ARCH", "gfx1100")
os.environ.setdefault("HIP_VISIBLE_DEVICES", "0")
os.environ.setdefault("HSA_ENABLE_SDMA", "0")
# 多卡 TP 必需
os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")
os.environ.setdefault("RCCL_NCCL_NCHANNELS", "4")
os.environ.setdefault("RCCL_NCCL_NSOCKETS_PERCHANNEL", "8")
os.environ.setdefault("NCCL_SOCKET_IFNAME", "lo")
os.environ.setdefault("HSA_ENABLE_INTERRUPTIBLE", "0")

import streamlit as st
import sys
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools  # noqa: F401  导入即触发所有工具注册到 registry
from inference.engine import InferenceEngine, InferenceConfig
from memory.manager import MemoryManager
from agent.core import RadeonAgent

st.set_page_config(
    page_title="AMD Radeon 本地智能体系统",
    page_icon="🤖",
    layout="wide",
)

@st.cache_resource
def init_engine():
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    model_config = config.get("model", {})
    inference_config = InferenceConfig(
        model_path=model_config.get("path", "./models/Qwen2.5-7B-Instruct"),
        n_ctx=model_config.get("n_ctx", 8192),
        temperature=model_config.get("temperature", 0.7),
        max_tokens=model_config.get("max_tokens", 4096),
        dtype=model_config.get("dtype", "float16"),
        gpu_memory_utilization=model_config.get("gpu_memory_utilization", 0.90),
        tensor_parallel_size=model_config.get("tensor_parallel_size", 1),
        pipeline_parallel_size=model_config.get("pipeline_parallel_size", 1),
    )
    
    engine = InferenceEngine(inference_config)
    return engine

@st.cache_resource
def init_memory():
    rag_config = {"chunk_size": 512, "chunk_overlap": 50, "top_k": 5}
    memory_manager = MemoryManager(
        index_path="./data/faiss_index",
        embedding_model="all-MiniLM-L6-v2",
        chunk_size=rag_config.get("chunk_size", 512),
        chunk_overlap=rag_config.get("chunk_overlap", 50),
        top_k=rag_config.get("top_k", 5),
    )
    return memory_manager

@st.cache_resource
def init_agent():
    engine = init_engine()
    memory_manager = init_memory()
    agent = RadeonAgent(engine, memory_manager)
    return agent

st.title("🤖 AMD Radeon 本地智能体系统")

with st.sidebar:
    st.header("系统信息")
    
    doc_count = 0
    try:
        memory_manager = init_memory()
        doc_count = memory_manager.get_document_count()
    except Exception as e:
        st.error(f"内存管理器初始化失败: {str(e)}")
    
    st.info(f"文档索引: {doc_count} 个文本块")
    
    st.header("上传文档")
    uploaded_files = st.file_uploader(
        "选择文档",
        type=["pdf", "docx", "md", "txt"],
        accept_multiple_files=True,
    )
    
    if uploaded_files:
        if st.button("上传并处理"):
            memory_manager = init_memory()
            save_dir = "./data/documents"
            os.makedirs(save_dir, exist_ok=True)
            
            for uploaded_file in uploaded_files:
                file_path = os.path.join(save_dir, uploaded_file.name)
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                added = memory_manager.add_document(file_path)
                st.success(f"已处理 {uploaded_file.name}: {added} 个文本块")
            
            st.rerun()
    
    st.header("操作")
    if st.button("清空对话"):
        agent = init_agent()
        agent.clear_memory()
        st.session_state.messages = []
        st.rerun()
    
    if st.button("重新加载模型"):
        st.cache_resource.clear()
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("请输入您的问题..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)
    
    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            try:
                agent = init_agent()
                response = agent.chat(prompt)
                
                st.markdown(response)
                
                st.session_state.messages.append({"role": "assistant", "content": response})
            except Exception as e:
                st.error(f"错误: {str(e)}")