"""
research.py — gives the agent WEB research: search + fetch.

Without this the agent can diagnose ("the fp8 type isn't in the enum") but not learn HOW to fix it —
a human would look up "how to add a quant type to ggml" or read an existing kernel PR. These tools let
it do exactly that: search the web and fetch pages/raw source (e.g. GitHub raw files, docs, PRs).

  web_search(query)  -> top result titles + urls + snippets
  web_fetch(url)     -> the page's text (HTML stripped), for reading a doc / PR / source file

Dependency-free (urllib + regex). Best-effort: returns an error string if offline / blocked, which the
agent can reason about rather than crash.
"""
import os, re, json, urllib.request, urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (optimizer-agent research)"}

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def _strip_html(html):
    html = re.sub(r"(?is)<(script|style|head|nav|footer)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html); html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"&lt;", "<", html);   html = re.sub(r"&gt;", ">", html)
    return re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", html)).strip()

RESEARCH_TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web. Use to find HOW to do something you don't know — e.g. how to add a "
                       "quant type to ggml, an existing kernel implementation, or documentation. Returns "
                       "titles, urls, and snippets; then web_fetch the promising url.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "web_fetch",
        "description": "Fetch a web page or raw source file and return its text (HTML stripped). Use on a url "
                       "from web_search, a GitHub raw file, a PR, or a documentation page (e.g. the ISA docs).",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}, "find": {"type": "string", "description": "optional: only return lines "
                    "around matches of this text (to focus a large page)"}}, "required": ["url"]}}},
]

def research_execute(fn, args):
    # Hyperloom runs fully offline by default. These are the only outbound calls in the
    # agent, they are never part of core inference, and they are opt-in so that a default
    # run makes no network requests at all.
    if os.environ.get("HYPERLOOM_ALLOW_WEB") != "1":
        return ("Web access is disabled. Hyperloom runs fully offline by default; "
                "set HYPERLOOM_ALLOW_WEB=1 to allow outbound lookups.")
    a = args or {}
    try:
        if fn == "web_search":
            q = urllib.parse.quote(a["query"])
            hits, seen = [], set()
            for base in ("https://lite.duckduckgo.com/lite/?q=", "https://html.duckduckgo.com/html/?q="):
                try:
                    html = _get(base + q)
                except Exception:
                    continue
                for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
                    href, title = m.group(1), _strip_html(m.group(2))
                    mm = re.search(r"uddg=([^&]+)", href)
                    if mm: href = urllib.parse.unquote(mm.group(1))
                    if not href.startswith("http") or "duckduckgo.com" in href: continue
                    if href in seen or len(title) < 4: continue
                    seen.add(href); hits.append({"title": title[:120], "url": href})
                    if len(hits) >= 6: break
                if hits: break
            return {"results": hits or "no results (or search blocked)"}
        if fn == "web_fetch":
            txt = _strip_html(_get(a["url"]))
            find = a.get("find")
            if find:
                lines = txt.splitlines()
                keep, idx = [], [i for i, l in enumerate(lines) if find.lower() in l.lower()]
                for i in idx[:8]:
                    keep += lines[max(0, i-3):i+6] + ["..."]
                txt = "\n".join(keep) if keep else txt
            return {"url": a["url"], "text": txt[:20000]}   # brain has 256K ctx — allow substantial docs
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e} (offline or blocked?)"}
    return {"error": f"unknown research tool {fn}"}

RESEARCH_PREAMBLE = (
    "You can RESEARCH THE WEB (web_search, web_fetch). When you hit something you don't know how to do — "
    "how to add a quant type to ggml, how a kernel is written, what a build error means — SEARCH for it and "
    "FETCH the best source (a GitHub file/PR, docs, the ISA reference). Do not grind the local code alone "
    "when the answer is a lookup away. Research the recipe, then apply it with edit_source + rebuild.")
