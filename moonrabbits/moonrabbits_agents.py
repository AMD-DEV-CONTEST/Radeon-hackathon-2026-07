#!/usr/bin/env python3
"""MoonRabbits four-expert chain, all local on Radeon via Ollama.

Historian (考据官): retrieves KB first; every claim MUST carry a [KB-id] citation.
Scientist (格物官): explains physics/chemistry, fact-checks the Historian.
Muse (灵感官): finds the emotional / creative angle.
Narrator (讲述者): the ONLY voice to the user; weaves everything into one story.

Usage:
  python moonrabbits_agents.py --query "用一段话向设计师介绍德化白瓷" --save outputs/run_001.json
"""
import argparse, json, sys, time, urllib.request
from pathlib import Path

BASE = Path("/workspace/persistent/moonrabbits")
CHROMA_DIR = BASE / "chroma"
INDEX_CACHE = BASE / "kb_text_index.json"
OLLAMA = "http://localhost:11434"
LLM = "qwen2.5:14b"
EMBED_MODEL = "bge-m3"


def ollama_post(endpoint: str, payload: dict, timeout: int = 600):
    req = urllib.request.Request(
        OLLAMA + endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def chat(system: str, user: str) -> str:
    res = ollama_post("/api/generate", {
        "model": LLM,
        "system": system,
        "prompt": user,
        "stream": False,
        "options": {"temperature": 0.4},
    })
    return res.get("response", "").strip()


def _vector_hits(coll, query: str, n: int = 5):
    emb = ollama_post("/api/embeddings", {"model": EMBED_MODEL, "prompt": query})["embedding"]
    res = coll.query(query_embeddings=[emb], n_results=min(n, coll.count()))
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        hits.append({"id": meta.get("kb_id", "?"), "source": meta.get("source", "?"),
                     "content": doc, "similarity": round(1 - dist, 3), "via": "向量"})
    return hits


def _load_text_index(coll):
    """Full-text index for keyword fallback; cached next to the chroma dir.
    Paged reads — chroma errors on 45k-row single get() (too many SQL variables)."""
    if INDEX_CACHE.exists():
        return json.loads(INDEX_CACHE.read_text(encoding="utf-8"))
    idx = []
    page = 5000
    total = coll.count()
    for off in range(0, total, page):
        data = coll.get(limit=page, offset=off, include=["documents", "metadatas"])
        for m, d in zip(data["metadatas"], data["documents"]):
            idx.append({"id": m.get("kb_id", "?"), "source": m.get("source", "?"), "content": d})
        print(f"  building keyword index... {min(off + page, total)}/{total}", flush=True)
    INDEX_CACHE.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    return idx


def _keyword_hits(coll, query: str, n: int = 5):
    """Substring fallback — critical for short proper nouns (人名/窑口/釉名)
    where dense vectors are weak (e.g. '何朝宗')."""
    idx = _load_text_index(coll)
    scored = []
    for item in idx:
        c = item["content"].count(query)
        if c:
            scored.append((c, len(item["content"]), item))
    scored.sort(key=lambda x: (-x[0], x[1]))  # most mentions, then shorter chunk
    out = []
    for c, _, item in scored[:n]:
        out.append({"id": item["id"], "source": item["source"], "content": item["content"],
                    "similarity": None, "via": f"关键词×{c}"})
    return out


def retrieve(query: str, n: int = 5):
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        coll = client.get_collection("cultural_kb")
    except Exception:
        print("!! knowledge base collection not found — run ingest_kb.py first")
        sys.exit(1)
    if coll.count() == 0:
        print("!! knowledge base is empty — run ingest_kb.py first")
        sys.exit(1)

    vec = _vector_hits(coll, query, n)
    kw = _keyword_hits(coll, query, n=3)
    # merge: keyword hits first (exact evidence), then vector hits, dedupe by id
    seen, merged = set(), []
    for h in kw + vec:
        if h["id"] in seen:
            continue
        seen.add(h["id"])
        merged.append(h)
        if len(merged) >= 8:
            break
    return merged


def kb_block(hits) -> str:
    lines = []
    for h in hits:
        lines.append(f"[{h['id']}]（来源：{h['source']}；命中方式：{h['via']}）{h['content']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--save", help="save full run to JSON")
    args = ap.parse_args()
    q = args.query
    t0 = time.time()
    run = {"query": q, "model": LLM, "agents": {}}

    print("=" * 70)
    print("【检索】查询知识库 ...")
    hits = retrieve(q)
    run["retrieval"] = hits
    for h in hits:
        sim = f"sim={h['similarity']}" if h.get("similarity") is not None else h["via"]
        print(f"  [{h['id']}] ({h['via']}, {sim}) {h['content'][:70]}...")
    kb = kb_block(hits)

    print("=" * 70)
    print("【考据官】先查依据，逐条挂文献 ...")
    historian_sys = (
        "你是 MoonRabbits 的考据官（Historian），文化遗产事实守门人。"
        "铁律：你的每一个事实句的句尾必须挂知识库条目编号，格式 [编号]。"
        "一个编号都没有的回答 = 失败回答。"
        "示范（照这个格式写）：德化白瓷始于宋代，明清达到高峰 [ocr_0043_c195]。其象牙白釉色温润 [kb_core_white_03]。"
        "其余规则：1) 标注'命中方式：关键词'的条目是全文精确匹配证据，引用优先级最高；"
        "2) 知识库里没有依据的内容，明确标注'（暂无文献支撑，仅为推测）'，绝不伪装成事实；"
        "3) 只基于给定知识库作答，不调用外部记忆编造；"
        "4) 用中文，条理清晰，不超过 400 字。"
    )
    historian = chat(historian_sys, f"知识库条目：\n{kb}\n\n用户问题：{q}")
    run["agents"]["historian"] = historian
    print(historian)

    print("=" * 70)
    print("【格物官】科学原理 + 事实核查 ...")
    scientist_sys = (
        "你是 MoonRabbits 的格物官（Scientist），负责物理化学原理与事实核查。"
        "规则：1) 检查考据官的回答中是否有朝代、窑口、工艺、化学成分等硬伤，逐条指出'无误'或'有误+理由'。"
        "2) 补充一个普通人能听懂的科学原理点（如釉色成因、烧成温度、光学特性）。"
        "3) 用中文，不超过 300 字。"
    )
    scientist = chat(scientist_sys, f"用户问题：{q}\n\n考据官的回答：\n{historian}")
    run["agents"]["scientist"] = scientist
    print(scientist)

    print("=" * 70)
    print("【灵感官】感性与创作角度 ...")
    muse_sys = (
        "你是 MoonRabbits 的灵感官（Muse），为创作者找感性角度。"
        "规则：1) 基于前两位的 factual 内容，给出 2-3 个有温度的叙事/创作角度（如器物与人的精神、东西方互鉴、光而不耀静水流深式的美学）。"
        "2) 不得引入新的'事实'，只做感受与联想。"
        "3) 用中文，不超过 250 字，语言克制不空洞。"
    )
    muse = chat(muse_sys, f"用户问题：{q}\n\n考据官：\n{historian}\n\n格物官：\n{scientist}")
    run["agents"]["muse"] = muse
    print(muse)

    print("=" * 70)
    print("【讲述者】最终成稿 ...")
    narrator_sys = (
        "你是 MoonRabbits 的讲述者（Narrator），唯一面向用户的声音。"
        "规则：1) 把三位专家的内容织成一个普通人听得懂、愿意传播的故事。"
        "2) 事实部分必须以考据官为准并保留文献编号引用；格物官指出过有误的内容不得出现。"
        "3) 口吻：轻松有温度、以小见大，不说教，不宣传片腔。"
        "4) 用中文，200-350 字。"
    )
    narrator = chat(narrator_sys,
                    f"用户问题：{q}\n\n考据官：\n{historian}\n\n格物官：\n{scientist}\n\n灵感官：\n{muse}")
    run["agents"]["narrator"] = narrator
    print(narrator)

    run["elapsed_sec"] = round(time.time() - t0, 1)
    print("=" * 70)
    print(f"耗时 {run['elapsed_sec']}s")

    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved -> {out}")


if __name__ == "__main__":
    main()
