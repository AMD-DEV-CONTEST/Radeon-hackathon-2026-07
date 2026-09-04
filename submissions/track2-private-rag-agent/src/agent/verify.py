# -*- coding: utf-8 -*-
"""引用可信度校验（groundedness check）：防止"模型编造来源/编造引用"。

思路（可解释、可演示，是评委看得懂的创新点）：
1. 解析回答里的 [来源:xxx] / [xxx.md] 引用标记 → 引用列表
2. 与"实际检索到的文档集合"对照 → 检查引用的来源是否真实存在
3. 对每个片段做"引用-原文"重叠度打分（字符 n-gram 重叠，文本先归一化去标点），
   标注「已支撑 / 部分支撑 / 无支撑」，并给出 grounding score

全部确定性实现（不额外调用 LLM），所以快且稳定。
"""
import re
from typing import List, Tuple

# 引用标记正则：[来源:文件名] 或 [文件名.md] 或 (来源:文件名)
CITE_RE = re.compile(r"\[来源[:：]?\s*([^\]\[]+?)\]|\[([^\[\]]+\.(?:md|pdf|docx|txt|csv|json|pptx|xlsx))\]")

# 停用词（不计入重叠度）
STOP = set("的了是和我他有这在那你一个也都很到对要在与及或者并而被于从把向对因为所以如果就这那是")

# 归一化：只保留 ASCII 字母数字 + 中文（去标点/空格/markdown 语法/emoji）
_NORM_RE = re.compile(r"[^0-9A-Za-z一-鿿]+")


def _normalize(text: str) -> str:
    return _NORM_RE.sub("", text).lower()


def extract_citations(answer: str) -> List[str]:
    """从回答文本中提取引用的来源文档名（去重）。"""
    cites = []
    for m in CITE_RE.finditer(answer):
        name = (m.group(1) or m.group(2) or "").strip()
        # 去掉可能的后缀噪声
        name = re.sub(r"[，。；,;）)\]].*$", "", name)
        if name and name not in cites:
            cites.append(name)
    return cites


def _ngrams(text: str, n: int = 3) -> set:
    """字符级 n-gram 集合（中文检索不用分词；3-gram 对改写鲁棒）。"""
    text = re.sub(r"\s+", "", text)
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def _split_sentences(text: str) -> List[str]:
    """按句读切分回答：句号/问号/叹号后，以及 markdown 换行（列表项天然一句）。

    不切分句子，而是"在边界处断开"：保留标点、去掉空白换行，
    这样最终答案里的每个列表项/段落都独立校验，逐句面板更细。
    """
    parts = re.split(r"(?<=[。！？!?])\s*|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def groundedness(answer: str, retrieved: List[str]) -> Tuple[float, List[dict]]:
    """评估回答的每个句子是否被检索原文支撑。

    Args:
        answer:     模型最终回答
        retrieved:  实际检索到的原文片段列表（来源文档文本）

    Returns:
        (score 0~1, [{"text": 句, "support": 0~1, "level": supported|partial|unsupported}])
    """
    if not retrieved:
        return 0.0, []
    pool = _ngrams(_normalize(" ".join(retrieved)))
    if not pool:
        return 0.0, []
    sentences = _split_sentences(answer)
    items = []
    scored = 0
    for s in sentences:
        s = s.strip()
        if not s or len(s) < 6:
            continue
        ngrams = _ngrams(_normalize(s))
        if not ngrams:
            continue
        hit = len(ngrams & pool) / len(ngrams)
        if hit > 0.30:
            level = "supported"
        elif hit > 0.12:
            level = "partial"
        else:
            level = "unsupported"
        items.append({"text": s[:120], "support": round(hit, 3), "level": level})
        scored += hit
    score = scored / len(items) if items else 0.0
    return round(score, 3), items


def verify_citations(answer: str, retrieved_sources: set) -> Tuple[float, List[dict]]:
    """校验回答中的引用来源是否真实存在于检索结果。

    Returns:
        (citation_precision 0~1, [{"cite":..., "grounded": bool}])
    """
    cites = extract_citations(answer)
    if not cites:
        # 无引用：不算"100% 有据"（那是虚报）；返回 None 表示"无可校验引用"，
        # UI 端显示"未引用来源"而非绿色满分。
        return None, [{"cite": "(无引用)", "grounded": None, "note": "回答未引用来源"}]
    checks = []
    ok = 0
    for c in cites:
        grounded = any(c in s for s in retrieved_sources) or any(
            (c in s) or (s in c) for s in retrieved_sources)
        checks.append({"cite": c, "grounded": bool(grounded)})
        ok += bool(grounded)
    return round(ok / len(cites), 3), checks


def format_verification(score: float, sentence_checks: List[dict],
                        cite_checks: List[dict]) -> str:
    """把校验结果渲染成给模型/UI 看的文本。"""
    _lvl = {"supported": "已支撑", "partial": "部分", "unsupported": "未"}
    lines = [f"引用校验：grounding={score}"]
    for chk in cite_checks:
        mark = "✓" if chk.get("grounded") else "✗"
        lines.append(f"  {mark} 引用 {chk['cite']} -> {'有据' if chk.get('grounded') else '无据'}")
    for it in sentence_checks:
        if it["level"] != "supported":
            lines.append(f"  [{_lvl.get(it['level'], '未')}] {it['text']}…")
    return "\n".join(lines)


if __name__ == "__main__":
    answer = "本项目基于 AMD ROCm 加速（来源:方案.md）。采用混合检索。"
    docs = ["AMD ROCm 加速推理", "混合检索 BM25"]
    print(extract_citations(answer))
    print(groundedness(answer, docs))
