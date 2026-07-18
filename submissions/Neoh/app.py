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

import logging
import sys
import subprocess
import argparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def run_streamlit(port: int = 7860):
    logger.info(f"Starting Streamlit server on port {port}")
    
    streamlit_path = os.path.join(os.path.dirname(__file__), "ui", "web_app.py")
    
    if not os.path.exists(streamlit_path):
        logger.error(f"Streamlit app not found: {streamlit_path}")
        sys.exit(1)
    
    try:
        result = subprocess.run(
            ["streamlit", "run", streamlit_path, "--server.port", str(port)],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Streamlit server failed: {str(e)}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Radeon-Assistant 应用入口")
    parser.add_argument(
        "--port",
        type=int,
        default=7860,
        help="Streamlit 服务端口"
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="web",
        choices=["web", "cli"],
        help="运行模式: web (Streamlit) 或 cli (命令行)"
    )
    args = parser.parse_args()

    if args.mode == "web":
        run_streamlit(args.port)
    elif args.mode == "cli":
        run_cli()


def run_cli():
    logger.info("Starting CLI mode")
    
    try:
        import yaml
        from inference.engine import InferenceEngine, InferenceConfig
        from memory.manager import MemoryManager
        from agent.core import RadeonAgent
        
        with open("config.yaml", "r", encoding="utf-8") as f:
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
        memory_manager = MemoryManager()
        agent = RadeonAgent(engine, memory_manager)
        
        logger.info("Agent initialized successfully")
        print("\n🤖 Radeon-Assistant CLI")
        print("输入 'quit' 或 'exit' 退出")
        print("输入 'task <任务>' 执行多步骤任务")
        print("-" * 50)
        
        while True:
            prompt = input("\n你: ")
            
            if prompt.lower() in ["quit", "exit", "q"]:
                print("再见!")
                break
            
            if prompt.lower().startswith("task "):
                task = prompt[5:].strip()
                print("正在执行任务...")
                result = agent.run_task(task)
                print(f"\n任务结果: {'完成' if result['success'] else '未完成'}")
                print(f"评估: {result['reflection'].get('reason', '')}")
            else:
                response = agent.chat(prompt)
                print(f"\n助手: {response}")
    
    except Exception as e:
        logger.error(f"CLI mode failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()