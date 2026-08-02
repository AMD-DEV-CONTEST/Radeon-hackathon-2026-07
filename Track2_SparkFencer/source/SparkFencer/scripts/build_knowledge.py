"""构建本地击剑知识库索引(knowledge/*.md -> knowledge/.index)。

用法: python scripts/build_knowledge.py [--test "查询"]
需要 ollama 已 pull 嵌入模型(默认 bge-m3)。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fencing_analysis.rag.store import KnowledgeStore, build_index


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-dir", default="knowledge")
    parser.add_argument("--embed-model", default="bge-m3")
    parser.add_argument("--provider", default="ollama", choices=["ollama", "llama.cpp"],
                         help="嵌入服务类型：ollama(/api/embed) 或 llama.cpp(/v1/embeddings)")
    parser.add_argument("--base-url", default=None, help="嵌入服务地址，默认 ollama 为 http://127.0.0.1:11434")
    parser.add_argument("--test", default=None, help="构建后跑一次检索测试")
    args = parser.parse_args()

    index_dir = build_index(args.knowledge_dir, embed_model=args.embed_model,
                            base_url=args.base_url, provider=args.provider)

    if args.test:
        store = KnowledgeStore(index_dir, base_url=args.base_url, provider=args.provider)
        print(f"\n检索: {args.test}")
        for r in store.search(args.test):
            print(f"  [{r['score']}] {r['source']}")


if __name__ == "__main__":
    main()
