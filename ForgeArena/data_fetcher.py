"""
ForgeArena Data Fetcher
Real-time web search + local knowledge base for financial analysis.
"""

import json, os, re, html
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.abspath(__file__))
KB_PATH = os.path.join(BASE, "data", "knowledge_base.jsonl")

# ── Web Search ──

def search_bing(query):
    """Search Bing (cn.bing.com) and return result HTML"""
    import requests
    url = "https://cn.bing.com/search?q=" + requests.utils.quote(query) + "&count=5"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    r = requests.get(url, headers=headers, timeout=6)  # Quick timeout to avoid hanging
    r.encoding = "utf-8"
    return r.text

def extract_bing_results(html_text):
    """Extract search result titles and snippets from Bing HTML"""
    soup = BeautifulSoup(html_text, "html.parser")
    results = []
    for li in soup.select("li.b_algo"):
        h2 = li.find("h2")
        if not h2:
            continue
        a = h2.find("a")
        title = a.get_text(strip=True) if a else ""
        url = a.get("href", "") if a else ""
        p = li.find("p")
        snippet = p.get_text(strip=True) if p else ""
        results.append({"title": title, "snippet": snippet[:300], "url": url})
    return results

def results_relevant(results, topic):
    """Rough check: do results look financially relevant?"""
    topic_lower = topic.lower()
    topic_keywords = set(topic_lower.split())
    finance_keywords = {"stock", "invest", "market", "fund", "portfolio", "share",
                        "trade", "capital", "bank", "finance", "technology", "chip",
                        "ai", "semiconductor", "hbm", "nvidia", "amd", "intel",
                        "hynix", "samsung", "tsmc", "seung", "bill", "hwang",
                        "持仓", "投资", "基金", "股票", "市场", "科技", "芯片",
                        "半导体", "人工智能", "产业链"}

    relevant_count = 0
    for r in results:
        combined = (r["title"] + " " + r["snippet"]).lower()
        # Check if topic keywords appear in result
        topic_match = sum(1 for kw in topic_keywords if kw in combined and len(kw) > 2)
        finance_match = sum(1 for kw in finance_keywords if kw in combined)
        if topic_match >= 1 or finance_match >= 2:
            relevant_count += 1

    # At least 1 result must look relevant
    return relevant_count >= 1

# ── Local Knowledge Base ──

def load_knowledge_base():
    """Load all knowledge entries from local JSONL"""
    entries = []
    if os.path.exists(KB_PATH):
        with open(KB_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except:
                        pass
    return entries

def match_knowledge(topic, entries):
    """Match knowledge entries by keywords"""
    topic_lower = topic.lower()
    matched = []
    for e in entries:
        keywords = [k.lower() for k in e.get("keywords", [])]
        if any(kw in topic_lower for kw in keywords):
            matched.append(e)
    return matched

# ── Main API ──

def fetch_context(topic):
    """
    Fetch context about a financial topic.
    Strategy: Prefer local knowledge base for known personas.
              Use web search for general topics.
    Returns dict with source info and context text.
    """
    result = {
        "topic": topic,
        "source": "no data",
        "source_label": "ℹ️ 未获取到外部数据",
        "context_text": "",
        "raw_results": [],
        "error": None
    }

    # Phase 1: Check local knowledge base first (for known personas)
    kb = load_knowledge_base()
    kb_matched = match_knowledge(topic, kb)

    # Phase 2: Try web search supplementary
    search_queries = [
        topic,
        topic + " 最新动态",
        topic + " 投资分析"
    ]
    web_contexts = []
    search_error = None
    for q in search_queries:
        try:
            html_text = search_bing(q)
            items = extract_bing_results(html_text)
            web_contexts.extend(items)
        except Exception as e:
            search_error = str(e)[:60]
            if not search_error:
                search_error = "timeout"
            continue  # Try next query on failure

    # Deduplicate
    seen = set()
    unique_web = []
    for w in web_contexts:
        if w["title"] not in seen:
            seen.add(w["title"])
            unique_web.append(w)

    web_relevant = results_relevant(unique_web, topic)

    # Phase 3: Build result
    if kb_matched:
        # Use KB as primary source
        result["source"] = "knowledge_base"
        result["source_label"] = "📚 本地知识库"
        context_parts = []
        for m in kb_matched[:3]:
            context_parts.append(f"- {m.get('title', '')}: {m.get('content', '')[:400]}")
        result["context_text"] = "\n".join(context_parts)

        # If web search also found relevant results, append them
        if web_relevant:
            result["source_label"] = "📚 本地知识库 + 📡 实时网络补充"
            for w in unique_web[:3]:
                context_parts.append(f"- [网络] {w['title']}: {w['snippet'][:150]}")
            result["context_text"] = "\n".join(context_parts)
            result["raw_results"] = unique_web[:3]

    elif web_relevant:
        # Use web search results as primary source
        result["source"] = "web"
        result["source_label"] = "📡 实时网络搜索（Bing）"
        result["raw_results"] = unique_web[:6]
        context_parts = []
        for w in unique_web[:4]:
            context_parts.append(f"- {w['title']}: {w['snippet'][:200]}")
        result["context_text"] = "\n".join(context_parts)

    else:
        # No useful data found
        result["source_label"] = "ℹ️ 基于模型知识分析（未获取到外部数据）"
        if search_error:
            result["error"] = search_error

    return result


if __name__ == "__main__":
    import sys
    topic = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Bill Seung"
    result = fetch_context(topic)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n--- Summary ---")
    print(f"Source: {result['source_label']}")
    if result["context_text"]:
        print(f"Context: {result['context_text'][:200]}...")
