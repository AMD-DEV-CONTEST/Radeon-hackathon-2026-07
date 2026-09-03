"""
memory.py — the agent builds and owns its own memory + RAG.

Not a knowledge base handed to it: a set of tools the agent uses to CONSTRUCT its own persistent
memory and a searchable knowledge corpus as it works, then RECALL from them before deciding.

  remember(note, tags)      -> write a durable memory (findings, dead-ends, decisions)
  recall(query)             -> retrieve its most relevant past memories
  ingest_knowledge(name,..) -> add a document (a writeup it read, an ISA note, its own log) to the corpus
  search_knowledge(query)   -> retrieve the most relevant chunks from what it has ingested

Storage is plain JSONL under memory/ (durable across runs, auditable). Retrieval is dependency-free
keyword/overlap scoring — a real RAG the agent grows itself; it can be upgraded to embeddings later
(e.g. via a lemonade embedding model) without changing the tool surface.
"""
import os, json, re, time, glob

DIR    = os.path.join(os.path.dirname(__file__), "memory")
MEM    = os.path.join(DIR, "memories.jsonl")
CORPUS = os.path.join(DIR, "corpus.jsonl")
os.makedirs(DIR, exist_ok=True)

_WORD = re.compile(r"[a-z0-9_.]+")
def _toks(s): return set(_WORD.findall((s or "").lower()))

def _score(q, text):
    qt, tt = _toks(q), _toks(text)
    if not qt or not tt: return 0.0
    return len(qt & tt) / (len(qt) ** 0.5)   # overlap, mildly length-normalized

def _append(path, obj):
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _load(path):
    if not os.path.exists(path): return []
    return [json.loads(l) for l in open(path) if l.strip()]

def _chunks(text, size=900):
    out, buf = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        # hard-split a giant block (e.g. source/minified with no blank lines) so retrieval is granular
        while len(para) > size:
            if buf: out.append(buf.strip()); buf = ""
            out.append(para[:size]); para = para[size:]
        if len(buf) + len(para) > size and buf:
            out.append(buf.strip()); buf = ""
        buf += para + "\n\n"
    if buf.strip():
        out.append(buf.strip())
    return out or [text[:size]]

MEM_TOOLS = [
    {"type": "function", "function": {
        "name": "remember",
        "description": "Store a durable memory: a finding, a measured result, a dead-end, or a decision. "
                       "Write these as you go so you never re-run what you already know and can justify choices.",
        "parameters": {"type": "object", "properties": {
            "note": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
            "required": ["note"]}}},
    {"type": "function", "function": {
        "name": "recall",
        "description": "Retrieve your most relevant past memories for a query (previous findings/decisions). "
                       "Call before experimenting to avoid repeating work.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "ingest_knowledge",
        "description": "Add a document to your searchable knowledge corpus. Give a local file path (e.g. a "
                       "writeup you want to reference) or raw text. Build your own RAG from sources you find useful.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "path": {"type": "string"}, "text": {"type": "string"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "search_knowledge",
        "description": "Retrieve the most relevant chunks from the knowledge corpus you have ingested.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "k": {"type": "integer"}}, "required": ["query"]}}},
]

def mem_execute(fn, args):
    a = args or {}
    if fn == "remember":
        _append(MEM, {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": a["note"], "tags": a.get("tags", [])})
        return {"remembered": True, "total_memories": len(_load(MEM))}
    if fn == "recall":
        rows = _load(MEM)
        ranked = sorted(rows, key=lambda r: _score(a["query"], r["note"] + " " + " ".join(r.get("tags", []))),
                        reverse=True)
        hits = [{"note": r["note"], "tags": r.get("tags", [])} for r in ranked[:5]
                if _score(a["query"], r["note"]) > 0]
        return {"recalled": hits or "no relevant memories yet"}
    if fn == "ingest_knowledge":
        text = a.get("text")
        if not text and a.get("path"):
            p = a["path"]
            if not os.path.exists(p): return {"error": f"no such file {p}"}
            text = open(p, errors="ignore").read()
        if not text: return {"error": "provide path or text"}
        n = 0
        for i, ch in enumerate(_chunks(text)):
            _append(CORPUS, {"src": a["name"], "i": i, "text": ch}); n += 1
        return {"ingested": a["name"], "chunks": n, "corpus_size": len(_load(CORPUS))}
    if fn == "search_knowledge":
        rows = _load(CORPUS)
        ranked = sorted(rows, key=lambda r: _score(a["query"], r["text"]), reverse=True)
        hits = [{"src": r["src"], "text": r["text"][:600]} for r in ranked[:a.get("k", 4)]
                if _score(a["query"], r["text"]) > 0]
        return {"results": hits or "corpus empty or no match — ingest_knowledge first"}
    return {"error": f"unknown memory tool {fn}"}

MEM_PREAMBLE = (
    "You build and own your MEMORY and KNOWLEDGE. As you work: remember() every finding, measurement, "
    "and dead-end; recall() before experimenting so you never repeat work; ingest_knowledge() the "
    "reference docs you find useful (e.g. optimization writeups, ISA notes) and search_knowledge() them "
    "to inform decisions. Grow your own RAG — do not rely on being told things you can look up or recall.")
