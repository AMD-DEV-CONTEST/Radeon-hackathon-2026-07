# -*- coding: utf-8 -*-
"""
rag/build_index.py — 药品目录向量库离线建库

流程（《设计文档.md》第 6.2 节）：
  drug_catalog.json → 文本化(可检索字段) → 本地 bge embedding
    → Chroma 持久化(带 metadata，余弦空间)

一次性执行，服务启动时直接加载，避免重复计算：
  python -m rag.build_index          # 建库（若已存在则重建）
  python -m rag.build_index --stat   # 仅查看现有库统计
"""

import os
import sys
import argparse

import rag  # noqa: F401  触发 HF_ENDPOINT 设置与 sys.path 注入
import config as cfg
from rag.retriever import load_catalog, doc_text, to_metadata, embed_documents


def build(reset: bool = True):
    import chromadb

    entries = load_catalog()
    if not entries:
        print(f"[build_index] 目录为空或读取失败: {cfg.DRUG_CATALOG_PATH}")
        return

    os.makedirs(cfg.CHROMA_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=cfg.CHROMA_DIR)

    if reset:
        try:
            client.delete_collection(cfg.CHROMA_COLLECTION)
            print(f"[build_index] 已删除旧集合 {cfg.CHROMA_COLLECTION}")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=cfg.CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    ids, docs, metadatas = [], [], []
    for i, e in enumerate(entries):
        text = doc_text(e)
        if not text:
            continue
        ids.append(f"drug-{i}")
        docs.append(text)
        metadatas.append(to_metadata(e))

    print(f"[build_index] 条目 {len(docs)}，正在用 {cfg.EMBEDDING_MODEL} 计算向量 …")
    embeddings = embed_documents(docs)

    collection.add(ids=ids, documents=docs, embeddings=embeddings, metadatas=metadatas)
    print(f"[build_index] 完成，集合 {cfg.CHROMA_COLLECTION} 共 {collection.count()} 条，持久化到 {cfg.CHROMA_DIR}")


def stat():
    import chromadb
    try:
        client = chromadb.PersistentClient(path=cfg.CHROMA_DIR)
        collection = client.get_collection(cfg.CHROMA_COLLECTION)
        print(f"[stat] 集合 {cfg.CHROMA_COLLECTION}: {collection.count()} 条 @ {cfg.CHROMA_DIR}")
    except Exception as e:
        print(f"[stat] 读取失败: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stat", action="store_true", help="仅查看现有库统计")
    ap.add_argument("--no-reset", action="store_true", help="不删除旧集合，追加写入")
    args = ap.parse_args()

    if args.stat:
        stat()
    else:
        build(reset=not args.no_reset)
