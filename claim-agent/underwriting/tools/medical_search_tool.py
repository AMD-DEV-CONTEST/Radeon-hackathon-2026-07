# -*- coding: utf-8 -*-
"""
underwriting/tools/medical_search_tool.py — 医学研究联网检索（双端并用，核心）

对齐 spec.md「医学研究联网检索（双端并用，核心）」需求：
对每个疾病/异常点同时调用 Exa（神经语义搜索）与 anysearch（health/academic 垂直域），
合并去重以最大化信息获取密度，任一端失败用另一端结果兜底。

双端并用策略（spec.md 核心成功因素）：
- Exa 端：神经语义搜索（``https://mcp.exa.ai/mcp``），对医学查询召回准确率高、免费、稳定。
- anysearch 端：调用 vendor ``anysearch_cli.py``，``search --domain health`` + ``--domain academic``
  两次子进程调用，匿名免费（``ANYSEARCH_API_KEY`` 可选提额）。
- 双端并发：所有 ``(disease, backend)`` 任务丢进同一个 ``ThreadPoolExecutor``
  （受 ``SEARCH_MAX_WORKERS`` 约束），按 url 合并去重并标注来源。
- 容错：任一端失败用另一端兜底（失败端 warning）；两端皆失败该疾病空 + error；
  单疾病失败不影响其他；不抛异常、不中断流水线。

输出 JSON schema（pipeline 依赖，严格遵守）：
{
  "references": [{"disease":"", "title":"", "url":"", "snippet":"", "source":"exa"|"health"|"academic"}],
  "warnings":   [{"disease":"", "backend":"exa"|"anysearch", "warning":""}],
  "errors":     [{"disease":"", "error":""}]
}

注：
- ``source`` 字段：Exa 来源记 ``"exa"``；anysearch 来源记其 source_domain（``"health"``/``"academic"``）。
- 同 url 多源命中时，保留先到的记录，并追加 ``sources``（list）与 ``diseases``（list）扩展字段
  以合并标注；不破坏上方 schema（pipeline 仅读取 schema 字段）。
"""

import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# 确保 ``import config as cfg`` 在直接执行本文件时也可用（参考 underwriting/__init__.py 模式）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_DIR = os.path.dirname(_THIS_DIR)            # underwriting/
_ROOT_DIR = os.path.dirname(_PKG_DIR)            # fake_ocr_test/
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import config as cfg  # noqa: E402

# 加入 tools/search 目录，便于 ``from web_search import web_search``
_TOOLS_SEARCH_DIR = os.path.join(_ROOT_DIR, "tools", "search")
if _TOOLS_SEARCH_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_SEARCH_DIR)


# ============================================================================
# SubTask 5.1: Exa 端封装
# ============================================================================

def _parse_exa_text(text: str, disease: str) -> list:
    """解析 Exa ``web_search`` 返回的结构化文本为 references 列表。

    Exa 返回文本格式（实测）::

        Title: 标题
        URL: https://...
        Published: 2026-01-23T03:31:03.000Z
        Author: N/A
        Highlights:
        高亮摘要片段1（可多行，含 ... 省略号分隔片段）
        ...
        高亮摘要片段2
        ...

        ---

        Title: 下一标题
        ...

    返回：``[{"disease":..., "title":..., "url":..., "snippet":..., "source":"exa"}, ...]``
    解析不出 url 的块：把整段作为 snippet、title 用首行，url 留空（不参与去重）。
    """
    refs: list = []
    if not text:
        return refs

    # 记录之间以单独一行 ``---`` 分隔（前后可能有空行）
    blocks = re.split(r'\n\s*-{3,}\s*\n', text)

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # 必须含 Title 或 URL 字样才视为一条记录
        if 'Title:' not in block and 'URL:' not in block:
            continue

        title = ''
        url = ''
        snippet_parts: list = []
        in_highlights = False
        for line in block.split('\n'):
            stripped = line.strip()
            if stripped.startswith('Title:'):
                title = stripped[len('Title:'):].strip()
                in_highlights = False
            elif stripped.startswith('URL:'):
                url = stripped[len('URL:'):].strip()
                in_highlights = False
            elif stripped.startswith('Published:'):
                in_highlights = False
            elif stripped.startswith('Author:'):
                in_highlights = False
            elif stripped.startswith('Highlights:'):
                in_highlights = True
                rest = stripped[len('Highlights:'):].strip()
                if rest:
                    snippet_parts.append(rest)
            elif in_highlights:
                if stripped:
                    snippet_parts.append(stripped)

        snippet = ' '.join(snippet_parts).strip()
        # 截断过长 snippet（pipeline 引用时只展示摘要，避免 LLM 上下文爆炸）
        if len(snippet) > 500:
            snippet = snippet[:500] + '...'

        # 解析不出 url：整段作为 snippet，title 用首行兜底
        if not url:
            first_line = block.split('\n', 1)[0].strip()
            # 去掉 "Title:" 前缀以复用为 title
            if first_line.lower().startswith('title:'):
                first_line = first_line[len('Title:'):].strip()
            title = title or first_line
            snippet = snippet or block[:500]
            url = ''

        if not title and not snippet:
            continue

        refs.append({
            "disease": disease,
            "title": title,
            "url": url,
            "snippet": snippet,
            "source": "exa",
        })

    return refs


def _search_exa(disease: str) -> tuple:
    """Exa 端封装：构造语义查询，调用 ``web_search``，解析返回文本为 references。

    返回 ``(refs, warnings)``：
    - ``refs``：references 列表（失败时为空）
    - ``warnings``：``[{"disease":..., "backend":"exa", "warning":...}]`` 失败信息

    设计为线程安全：所有失败信息通过返回值传递，不依赖 ``warnings`` 模块
    （``warnings.catch_warnings`` 是 thread-local，跨线程捕获不可靠）。
    """
    refs: list = []
    warnings_list: list = []

    try:
        from web_search import web_search  # type: ignore
    except Exception as e:  # noqa: BLE001
        warnings_list.append({
            "disease": disease,
            "backend": "exa",
            "warning": f"import web_search failed: {e}",
        })
        return refs, warnings_list

    query = f"{disease} 核保风险 最新研究 指南"
    try:
        # web_search 内部硬编码 timeout=30，与 cfg.EXA_TIMEOUT 对齐
        text = web_search(query, num_results=cfg.EXA_NUM_RESULTS)
    except Exception as e:  # noqa: BLE001
        warnings_list.append({
            "disease": disease,
            "backend": "exa",
            "warning": f"web_search call failed: {e}",
        })
        return refs, warnings_list

    if not text:
        warnings_list.append({
            "disease": disease,
            "backend": "exa",
            "warning": "empty response from Exa",
        })
        return refs, warnings_list

    try:
        refs = _parse_exa_text(text, disease)
    except Exception as e:  # noqa: BLE001
        warnings_list.append({
            "disease": disease,
            "backend": "exa",
            "warning": f"parse failed: {e}",
        })
        refs = []

    if not refs:
        # 调用成功但解析出 0 条：记录 warning 便于排查
        warnings_list.append({
            "disease": disease,
            "backend": "exa",
            "warning": f"parsed 0 references from {len(text)} chars",
        })

    return refs, warnings_list


# ============================================================================
# SubTask 5.2: anysearch 端封装
# ============================================================================

def _parse_anysearch_text(text: str, disease: str, source_domain: str) -> list:
    """解析 anysearch CLI 的 markdown 输出为 references 列表。

    anysearch CLI ``search`` 子命令输出格式（实测）::

        ## Search Results (N results, XXXXms)

        ### 1. 标题
        - **URL**: https://...
        - 摘要文本（可多行，可能以 ## 开头）
        - Read more

        ### 2. 标题
        - **URL**: https://...
        - Dec 2, 2017 — 摘要文本

    返回：``[{"disease":..., "title":..., "url":..., "snippet":..., "source":source_domain}, ...]``
    """
    refs: list = []
    if not text:
        return refs

    # 按 ``### N. `` 切分记录（保留分隔符，前向断言）
    blocks = re.split(r'\n(?=###\s+\d+\.)', text)

    for block in blocks:
        block = block.strip()
        if not block.startswith('###'):
            continue

        lines = block.split('\n')
        title = ''
        url = ''
        snippet_lines: list = []

        # 第一行：### N. Title
        m = re.match(r'^###\s+\d+\.\s*(.*)$', lines[0])
        if m:
            title = m.group(1).strip()

        for line in lines[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            # URL 行：``- **URL**: https://...``
            mu = re.match(r'^-\s*\*\*URL\*\*\s*[:：]\s*(.+)$', stripped)
            if mu:
                url = mu.group(1).strip()
                continue
            # 跳过 ``- Read more`` 等无内容行
            if stripped.lower() in ('- read more', 'read more'):
                continue
            # 摘要行：去掉前导的 ``- `` 或 ``- ## ``
            ms = re.match(r'^-\s+(.*)$', stripped)
            if ms:
                content = ms.group(1).strip()
                # 去掉前导的 ``##`` 等标题标记
                content = re.sub(r'^#+\s*', '', content)
                if content:
                    snippet_lines.append(content)
            else:
                # 非列表行内容也作为摘要
                snippet_lines.append(stripped)

        snippet = ' '.join(snippet_lines).strip()
        if len(snippet) > 500:
            snippet = snippet[:500] + '...'

        if not title and not snippet and not url:
            continue

        refs.append({
            "disease": disease,
            "title": title,
            "url": url,
            "snippet": snippet,
            "source": source_domain,
        })

    return refs


def _run_anysearch_subprocess(query: str, domain: str, max_results: int) -> str:
    """运行 anysearch_cli.py 子进程并返回 stdout 文本。

    失败时抛出异常，由上层捕获记为 warning。
    使用当前 ``sys.executable`` 作为 Python 解释器，``cfg.ANYSEARCH_CLI_PATH`` 指定脚本路径。
    若 ``cfg.ANYSEARCH_API_KEY`` 非空则透传到子进程环境变量。
    """
    cli_path = cfg.ANYSEARCH_CLI_PATH
    if not os.path.isfile(cli_path):
        raise FileNotFoundError(f"anysearch_cli.py not found at: {cli_path}")

    cmd = [
        sys.executable,
        cli_path,
        "search",
        query,
        "--domain", domain,
        "--max_results", str(max_results),
    ]

    env = os.environ.copy()
    if cfg.ANYSEARCH_API_KEY:
        env["ANYSEARCH_API_KEY"] = cfg.ANYSEARCH_API_KEY

    # 强制 utf-8 解码，避免 Windows GBK 解码中文失败
    timeout = max(cfg.EXA_TIMEOUT + 30, 60)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=env,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr = (result.stderr or '').strip()[:300]
        raise RuntimeError(f"anysearch exit={result.returncode}: {stderr}")
    return result.stdout or ''


def _search_anysearch(disease: str) -> tuple:
    """anysearch 端封装：调用 ``--domain health`` + ``--domain academic``，返回 references。

    返回 ``(refs, warnings)``：
    - ``refs``：references 列表（两个 domain 合并；都失败时为空）
    - ``warnings``：``[{"disease":..., "backend":"anysearch", "warning":...}]`` 失败信息

    单个 domain 失败不阻塞另一个 domain；两个都失败则 refs 为空，由上层标 error。
    """
    refs: list = []
    warnings_list: list = []

    query = f"{disease} 核保 风险"

    for domain in ("health", "academic"):
        try:
            text = _run_anysearch_subprocess(query, domain, max_results=3)
            domain_refs = _parse_anysearch_text(text, disease, source_domain=domain)
            refs.extend(domain_refs)
            if not domain_refs:
                warnings_list.append({
                    "disease": disease,
                    "backend": "anysearch",
                    "warning": f"domain={domain} parsed 0 references from {len(text)} chars",
                })
        except Exception as e:  # noqa: BLE001
            warnings_list.append({
                "disease": disease,
                "backend": "anysearch",
                "warning": f"domain={domain} failed: {e}",
            })
            # 单 domain 失败不阻塞另一个 domain，继续循环

    return refs, warnings_list


# ============================================================================
# SubTask 5.3: 双端并用编排 + 去重
# ============================================================================

def _merge_and_dedup(per_disease_results: dict) -> list:
    """合并多疾病的双端结果，按 url 去重。

    - 同 url 多次出现：保留先到的记录，合并 ``sources``（list）与 ``diseases``（list）扩展字段
    - 空 url：不去重，全部保留（不同疾病的高亮摘要可能无 url，不应被合并丢弃）

    ``per_disease_results`` 顺序为输入 ``diseases`` 顺序，每个 disease 内 Exa 在前、anysearch 在后，
    因此「先到的」是确定性的（不受线程完成顺序影响）。
    """
    merged: list = []
    seen_urls: dict = {}  # url -> index in merged

    for disease, refs in per_disease_results.items():
        for ref in refs:
            url = (ref.get('url') or '').strip()
            if url and url in seen_urls:
                idx = seen_urls[url]
                existing = merged[idx]
                # 合并 source 标注：累积到 sources 列表
                sources = existing.setdefault('sources', [existing['source']])
                if ref['source'] not in sources:
                    sources.append(ref['source'])
                # 合并 disease 标注（同 url 可能命中多个疾病）
                diseases = existing.setdefault('diseases', [existing['disease']])
                if ref['disease'] not in diseases:
                    diseases.append(ref['disease'])
                # 若已有 snippet 为空但新 snippet 非空，则补充
                if not existing.get('snippet') and ref.get('snippet'):
                    existing['snippet'] = ref['snippet']
                continue
            # 新 url 或空 url：加入 merged
            new_ref = dict(ref)
            if url:
                seen_urls[url] = len(merged)
            merged.append(new_ref)

    return merged


def search_medical(diseases: list, extract: dict = None) -> dict:
    """对每个疾病同时调用 Exa + anysearch 双端检索，合并去重。

    参数：
        diseases: 疾病/异常点名称列表，如 ``["高血压", "2型糖尿病"]``
        extract: 可选的报告提取结果（保留接口，当前未使用；后续可按需对关键引用调 ``extract`` 抓全文）

    返回（严格遵守 schema，pipeline 依赖）::

        {
          "references": [{"disease":..., "title":..., "url":..., "snippet":..., "source":"exa"|"health"|"academic"}],
          "warnings":   [{"disease":..., "backend":"exa"|"anysearch", "warning":...}],
          "errors":     [{"disease":..., "error":...}]
        }

    编排（spec.md「双端并发检索」）：
        - 所有 ``(disease, backend)`` 任务丢进同一个 ``ThreadPoolExecutor``
          （``max_workers=cfg.SEARCH_MAX_WORKERS``）；多疾病时各疾病的双端查询整体并发。
        - 收集每个疾病的 Exa 结果 + anysearch 结果，按 url 全局合并去重并标注来源。

    容错（spec.md「单端失败兜底」）：
        - 任一端失败：用另一端结果兜底，失败端在 warnings 记录。
        - 两端皆失败：该疾病 references 为空，在 errors 记录，不中断流水线。
        - 单疾病失败不影响其他疾病。
        - 全程不抛异常。
    """
    if not diseases:
        return {"references": [], "warnings": [], "errors": []}

    # 每个 disease 的双端结果：{"disease": {"exa": [...], "anysearch": [...]}}
    per_disease: dict = {d: {"exa": [], "anysearch": []} for d in diseases}
    all_warnings: list = []

    # 任务粒度：(disease, backend)，所有任务丢进同一个线程池
    backend_fns = {"exa": _search_exa, "anysearch": _search_anysearch}
    tasks: list = []
    for disease in diseases:
        for backend in ("exa", "anysearch"):
            tasks.append((disease, backend))

    max_workers = max(1, cfg.SEARCH_MAX_WORKERS)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task: dict = {}
        for disease, backend in tasks:
            fn = backend_fns[backend]
            fut = executor.submit(fn, disease)
            future_to_task[fut] = (disease, backend)

        for fut in as_completed(future_to_task):
            disease, backend = future_to_task[fut]
            try:
                refs, warns = fut.result()
                per_disease[disease][backend] = refs or []
                all_warnings.extend(warns or [])
            except Exception as e:  # noqa: BLE001
                # 兜底：函数内部已 try/except，理论上不会到这；保留以防意外
                per_disease[disease][backend] = []
                all_warnings.append({
                    "disease": disease,
                    "backend": backend,
                    "warning": f"unexpected executor exception: {e}",
                })

    # 合并 + 标注 errors（两端皆失败的疾病）
    per_disease_results: dict = {}
    errors: list = []
    for disease in diseases:
        exa_refs = per_disease[disease]["exa"]
        any_refs = per_disease[disease]["anysearch"]
        per_disease_results[disease] = exa_refs + any_refs
        if not exa_refs and not any_refs:
            # 两端皆失败：在 errors 记录该疾病
            disease_warns = [w for w in all_warnings if w.get("disease") == disease]
            if disease_warns:
                fail_msgs = [f"{w['backend']}: {w['warning']}" for w in disease_warns]
                err_msg = "Both backends failed: " + " | ".join(fail_msgs)
            else:
                err_msg = "Both backends returned no results"
            errors.append({"disease": disease, "error": err_msg})

    references = _merge_and_dedup(per_disease_results)

    return {
        "references": references,
        "warnings": all_warnings,
        "errors": errors,
    }


# ============================================================================
# 可选：LangChain @tool 包装
# ============================================================================

try:
    from langchain.tools import tool as _lc_tool  # type: ignore
except Exception:  # noqa: BLE001
    _lc_tool = None

if _lc_tool is not None:
    @_lc_tool
    def medical_search_tool(diseases: list, extract: dict = None) -> dict:
        """医学研究联网检索工具（双端并用：Exa + anysearch）。

        对每个疾病/异常点同时调用 Exa 神经语义搜索与 anysearch 的 health/academic 垂直域，
        合并去重并标注来源；任一端失败用另一端结果兜底。

        参数：
            diseases: 疾病/异常点名称列表，如 ``["高血压", "2型糖尿病"]``
            extract: 可选的报告提取结果（保留接口，当前未使用）

        返回：
            dict 含 references（合并去重后的医学参考引用列表）、warnings、errors。
            每条 reference 含 disease/title/url/snippet/source 字段，
            source 取值 ``"exa"`` / ``"health"`` / ``"academic"``。
        """
        return search_medical(diseases, extract)
else:
    medical_search_tool = None  # type: ignore


# ============================================================================
# 直接运行做联网验证
# ============================================================================

if __name__ == "__main__":
    import io
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    test_diseases = sys.argv[1:] if len(sys.argv) > 1 else ["高血压"]
    print(f"=== search_medical({test_diseases}) ===")
    result = search_medical(test_diseases)

    refs = result["references"]
    warns = result["warnings"]
    errs = result["errors"]
    print(f"\n[Summary] references={len(refs)}, warnings={len(warns)}, errors={len(errs)}")

    # 来源分布
    source_count: dict = {}
    for r in refs:
        s = r.get('source', 'unknown')
        source_count[s] = source_count.get(s, 0) + 1
    print(f"[Source distribution] {source_count}")

    # url 去重检查
    urls = [r.get('url', '') for r in refs if r.get('url')]
    print(f"[URL dedup check] total non-empty urls={len(urls)}, unique urls={len(set(urls))}")

    # 按疾病分布
    disease_count: dict = {}
    for r in refs:
        d = r.get('disease', '')
        disease_count[d] = disease_count.get(d, 0) + 1
    print(f"[Disease distribution] {disease_count}")

    print("\n[References sample] (first 5)")
    for i, r in enumerate(refs[:5]):
        print(f"\n--- #{i + 1} ---")
        print(f"  disease: {r.get('disease', '')}")
        print(f"  title:   {r.get('title', '')[:80]}")
        print(f"  url:     {r.get('url', '')}")
        print(f"  source:  {r.get('source', '')}")
        if 'sources' in r:
            print(f"  sources: {r['sources']}")
        snippet = r.get('snippet', '')
        print(f"  snippet: {snippet[:120]}{'...' if len(snippet) > 120 else ''}")

    if warns:
        print("\n[Warnings]")
        for w in warns:
            print(f"  - {w}")

    if errs:
        print("\n[Errors]")
        for e in errs:
            print(f"  - {e}")
