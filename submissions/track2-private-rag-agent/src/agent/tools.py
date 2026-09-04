# -*- coding: utf-8 -*-
"""工具注册与调用：Agent 通过工具完成"感知→行动"闭环。

工具集（5 个）：
  rag_search         混合检索知识库（BM25+向量+重排），返回带分数与来源的片段
  read_doc           读取文档全文
  list_docs          列出知识库文档
  summarize          总结指定文档（分层摘要）
  web_search_offline 离线网页检索（检索本地缓存的网页，外网不可用时不报错）

每个工具返回纯文本，供 LLM 理解后续行动。
"""
import os
import re
from typing import Callable, Dict

import yaml

with open("config.yaml", "r", encoding="utf-8") as _f:
    CFG = yaml.safe_load(_f)

DOCS_DIR = CFG.get("rag", {}).get("docs_dir", "./data/docs")
WEB_DIR = CFG.get("tools", {}).get("web_cache_dir", "./data/web")


class Tool:
    def __init__(self, name: str, description: str, run: Callable, parameters: dict):
        self.name = name
        self.description = description
        self.run = run
        self.parameters = parameters

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools.get(name)

    def schemas(self) -> list:
        return [t.schema() for t in self._tools.values()]

    def names(self) -> str:
        return ", ".join(self._tools.keys())

    def call(self, name: str, arguments: dict) -> str:
        tool = self.get(name)
        if not tool:
            return f"[错误] 工具 {name} 不存在"
        try:
            return str(tool.run(**arguments))
        except Exception as e:
            return f"[工具执行错误] {e}"


def build_tools(rag) -> ToolRegistry:
    """基于 RAG 构建工具集。"""
    reg = ToolRegistry()

    def rag_search(query: str, top_k: int = 4):
        hits = rag.search(query, top_k)
        if not hits:
            return "知识库中没有相关内容。"
        lines = []
        for i, (t, src, sc) in enumerate(hits, 1):
            lines.append(f"[来源:{src} 相关度:{sc}]\n{t}")
        return "\n\n".join(lines)

    reg.register(Tool(
        name="rag_search",
        description=("在私有知识库中混合检索（语义+关键词+重排）与问题最相关的文档片段。"
                     "当问题涉及你的个人/团队文档内容时，必须先调用它。"),
        run=rag_search,
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "检索关键词或问题"},
            "top_k": {"type": "integer", "description": "返回条数，默认4，最多10"}},
            "required": ["query"]},
    ))

    def read_doc(doc: str):
        path = os.path.join(DOCS_DIR, doc)
        if not os.path.exists(path):
            return f"[错误] 文档 {doc} 不存在，可用文档: {list_docs()}"
        try:
            text = rag.get_document(doc, limit=4000)
            return text or "[空文档]"
        except Exception:
            from .parser import read_document
            return read_document(path)[:4000]

    reg.register(Tool(
        name="read_doc",
        description="读取指定文档的完整内容（前4000字）。文档名来自 list_docs 或 rag_search 的来源标注。",
        run=read_doc,
        parameters={"type": "object", "properties": {
            "doc": {"type": "string", "description": "文档文件名，如 report.pdf"}},
            "required": ["doc"]},
    ))

    def list_docs():
        docs = rag.list_documents()
        if not docs:
            return "知识库为空，请先导入文档。"
        total = sum(d["chunks"] for d in docs)
        lines = [f"共 {len(docs)} 个文档 / {total} 个片段："]
        for d in docs:
            lines.append(f"  · {d['doc']}（{d['chunks']} 片段）")
        return "\n".join(lines)

    reg.register(Tool(
        name="list_docs",
        description="列出知识库中已导入的文档及片段统计。",
        run=list_docs,
        parameters={"type": "object", "properties": {}},
    ))

    def summarize(doc: str, depth: str = "标准"):
        """对单个文档做分层摘要（map-reduce）。"""
        text = rag.get_document(doc, limit=8000)
        if not text:
            return f"[错误] 文档 {doc} 不可读或为空"
        from .llm import LLMBackend
        llm = LLMBackend()
        # map：分段摘要
        step = 2000
        parts = [text[i:i + step] for i in range(0, len(text), step)]
        chunks = []
        for i, p in enumerate(parts):
            r = llm.chat([{"role": "system", "content":
                           f"请用不超过150字概括以下文档片段（第{i + 1}/{len(parts)}段），"
                           "保留关键事实、数字、专有名词，不要遗漏。"},
                          {"role": "user", "content": p}],
                         temperature=0.2, max_tokens=300)
            chunks.append(r["content"])
        # reduce：合并成总结
        body = "\n".join(f"- {c}" for c in chunks)
        style = "详细、结构化，带要点列表" if depth == "详细" else "精炼，重点突出"
        r = llm.chat([{"role": "system", "content":
                       f"你是文档总结专家。把下面的分段摘要整合成一篇{style}总结（中文）。"
                       "开头一句概括全文主旨，随后分点列出要点，结尾给出3个最值得注意的结论。"},
                      {"role": "user", "content": f"《{doc}》分段摘要：\n{body}"}],
                     temperature=0.2, max_tokens=900)
        return f"【《{doc}》总结】\n{r['content']}"

    reg.register(Tool(
        name="summarize",
        description="总结指定文档的完整内容（分层 map-reduce 摘要）。当需要整体把握某文档时使用。",
        run=summarize,
        parameters={"type": "object", "properties": {
            "doc": {"type": "string", "description": "文档文件名"},
            "depth": {"type": "string", "description": "标准/详细", "enum": ["标准", "详细"]}},
            "required": ["doc"]},
    ))

    def web_search_offline(query: str, top_k: int = 3):
        """离线网页检索：在本地缓存目录 data/web/ 里做关键词匹配（无需外网）。"""
        if not os.path.isdir(WEB_DIR):
            return ("[提示] 当前处于完全离线模式，无本地网页缓存目录 "
                    f"({WEB_DIR})。可放置下载好的网页到该目录供离线检索。")
        terms = [t for t in re.findall(r"[a-z0-9_一-鿿]{2,}", query.lower())]
        scored = []
        for fname in os.listdir(WEB_DIR):
            path = os.path.join(WEB_DIR, fname)
            if not os.path.isfile(path) or fname.startswith("."):
                continue
            try:
                txt = open(path, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            score = sum(txt.lower().count(t) for t in terms)
            if score > 0:
                scored.append((score, fname, txt))
        scored.sort(reverse=True, key=lambda x: x[0])
        if not scored:
            return "本地网页缓存中没有与查询匹配的内容。"
        out = []
        for score, fname, txt in scored[:top_k]:
            # 截取命中区域上下文
            snippet = txt[:400]
            for t in terms:
                idx = txt.lower().find(t)
                if idx >= 0:
                    snippet = txt[max(0, idx - 100):idx + 300]
                    break
            out.append(f"[来源(离线网页):{fname} 匹配:{score}]\n{snippet}")
        return "\n\n".join(out)

    reg.register(Tool(
        name="web_search_offline",
        description=("离线网页检索：搜索本地缓存的网页内容（data/web 目录）。"
                     "当问题需要实时资讯，但环境完全离线时使用。"),
        run=web_search_offline,
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "top_k": {"type": "integer", "description": "返回条数，默认3"}},
            "required": ["query"]},
    ))

    return reg
