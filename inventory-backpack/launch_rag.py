"""Launch RAG"""
from dotenv import load_dotenv
load_dotenv()
import argparse
import asyncio
import getpass
import os

from src.agent.specialists.knowledge_assistant import KnowledgeAssistant
from src.utils.config_loader import get_remote_config, load_config

async def main():
    parser = argparse.ArgumentParser(description="Motus Agent")
    parser.add_argument("--endpoint", help="覆盖 endpoint")
    parser.add_argument("--api-key", help="API Key")
    parser.add_argument("--model", help="覆盖模型")
    parser.add_argument("--config", default="config/agent.yaml", help="配置文件路径")
    args = parser.parse_args()
    # Load configuration
    full_config = load_config(args.config)
    remote_config = get_remote_config(args.config)
    
    # Extract parameters
    endpoint = args.endpoint or remote_config.get("endpoint")
    api_key = args.api_key or remote_config.get("api_key") or os.environ.get("HF_TOKEN")
    model = args.model or remote_config.get("model")
    
    if not api_key:
        api_key = getpass.getpass("请输入 API Key: ")
    
    if not endpoint or not api_key or not model:
        raise ValueError("缺少必要参数")
    
    # Clean up residual ${}
    if endpoint.startswith("${"):
        raise ValueError(f"endpoint 未解析: {endpoint}")
    
    print(f"🚀 连接: {endpoint}")
    print(f"🤖 模型: {model}")

    # Key: assemble complete configuration
    import copy
    complete_config = copy.deepcopy(full_config)
    
    # Inject/override remote configuration
    complete_config["remote"] = {
        **complete_config.get("remote", {}),
        "endpoint": endpoint,
        "api_key": api_key,
        "model": model,
        "timeout": remote_config.get("timeout", 45),
    }
    
    # Inject/override rag.embedding (if YAML uses environment variables or placeholders)
    if "rag" in complete_config and "embedding" in complete_config["rag"]:
        complete_config["rag"]["embedding"] = {
            **complete_config["rag"]["embedding"],
            "api_key": api_key,
        }
        # If api_url is not in config, fall back to environment variable
        if not complete_config["rag"]["embedding"].get("api_url"):
            complete_config["rag"]["embedding"]["api_url"] = os.environ.get("EMBEDDING_API_URL")
    
    # Initialize
    assistant = KnowledgeAssistant()
    assistant.initialize(config=complete_config)
    
    await assistant.start()

    # Test
    result = await assistant.process("AMD GPU 怎么优化？")
    
    print(f"\n{'='*40}")
    print(f"模式: {result.get('mode', 'unknown')}")
    print(f"来源: {result.get('sources', [])[:2]}")
    print(f"💡 {result['answer'][:500]}...")

    await assistant.stop()


if __name__ == "__main__":
    asyncio.run(main())