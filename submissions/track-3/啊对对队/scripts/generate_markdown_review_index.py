from __future__ import annotations

import os
import re
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
DOCS = PROJECT / "docs"
OUTPUT = DOCS / "MD_REVIEW_INDEX_EN_CN.md"

PRIORITY = [
    "README.md",
    "PROJECT_DESCRIPTION_EN_CN.md",
    "PROJECT_DESCRIPTION.md",
    "PROJECT_DESCRIPTION_CN.md",
    "docs/PR_DESCRIPTION_READY.md",
    "docs/FINAL_SUBMISSION_AUDIT.md",
    "docs/RESULT_ATTRIBUTION.md",
    "docs/SUBMISSION_CHECKLIST.md",
    "docs/AGENT_MODEL_ARCHITECTURE.md",
    "docs/TRAINING_EVIDENCE.md",
    "docs/ABLATION_RESULTS.md",
    "docs/SIM_TO_REAL_STATUS.md",
    "docs/DATASET_CARD.md",
    "docs/DATASET_CARD_CN.md",
    "docs/MODEL_CARD.md",
    "docs/MODEL_CARD_CN.md",
    "data/README.md",
    "data/HUGGINGFACE_UPLOAD_GUIDE_EN_CN.md",
    "videos/README.md",
    "videos/UPLOAD_COPY.md",
]


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def has_english(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]{3,}", text))


def language_status(relative: str, text: str, all_paths: set[str]) -> str:
    path = Path(relative)
    if path.stem.endswith("_EN_CN"):
        return "Bilingual in one / 单文件双语"
    if path.stem.endswith("_CN"):
        counterpart = str(path.with_name(path.stem[:-3] + path.suffix)).replace("\\", "/")
        if counterpart in all_paths:
            return "Bilingual pair: CN / 双语配对：中文"
        return "Chinese-led / 中文为主"

    cn_pair = str(path.with_name(path.stem + "_CN" + path.suffix)).replace("\\", "/")
    if cn_pair in all_paths:
        return "Bilingual pair: EN / 双语配对：英文"
    if has_chinese(text) and has_english(text):
        return "Bilingual in one / 单文件双语"
    if has_chinese(text):
        return "Chinese-led / 中文为主"
    return "English only / 仅英文"


def category(relative: str) -> str:
    if relative in PRIORITY:
        return "Submission review / 提交主审"
    if relative.startswith(("docs/", "evidence/", "data/", "videos/")):
        return "Evidence or report / 证据或报告"
    if relative.startswith(("papers/", "submission_materials/")):
        return "Research draft / 研究草稿"
    return "Runtime or internal / 运行或内部"


def main() -> None:
    files = sorted(PROJECT.rglob("*.md"))
    relative_files = [p.relative_to(PROJECT).as_posix() for p in files]
    all_paths = set(relative_files)
    priority_order = {name: index for index, name in enumerate(PRIORITY)}
    relative_files.sort(key=lambda p: (priority_order.get(p, len(PRIORITY)), p.casefold()))

    rows: list[str] = []
    counts: dict[str, int] = {}
    for relative in relative_files:
        source = PROJECT / relative
        text = source.read_text(encoding="utf-8", errors="replace")
        status = language_status(relative, text, all_paths)
        counts[status] = counts.get(status, 0) + 1
        href = os.path.relpath(source, DOCS).replace("\\", "/")
        rows.append(f"| [{relative}]({href}) | {category(relative)} | {status} |")

    status_summary = "; ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
    content = f"""# Markdown Review Index / Markdown 审阅索引

## Scope / 范围

Inventory date / 盘点日期: **2026-08-06**. This project contains **{len(relative_files)} Markdown files**. The table below links every file and marks whether Chinese and English are in one file, split into a pair, or not yet paired.

项目共有 **{len(relative_files)} 个 Markdown 文件**。下表逐一提供可点击链接，并标记中英内容是位于同一文件、拆分为配对文件，还是尚未配对。

Language summary / 语言统计: {status_summary}

## Review Rule / 审阅规则

- Review `Submission review / 提交主审` first. These are the files intended for judges. / 优先审阅“提交主审”，这些文件面向评委。
- `Evidence or report / 证据或报告` supports traceability; old experimental records may use historical datasets and must not replace current headline results. / “证据或报告”用于追溯；旧实验可能使用历史数据，不能替代当前主结果。
- Current headline boundaries: scripted Agent **8/10**; hybrid Agent+VLA offline envelope **42/42 only**; strict pure VLA **0/3**; Sim-to-Real **not performed**. / 当前主结果边界：脚本 Agent **8/10**；混合 Agent+VLA 仅离线包络 **42/42**；严格纯 VLA **0/3**；Sim-to-Real **未执行**。

## Complete Inventory / 完整清单

| File / 文件 | Category / 类别 | Language status / 语言状态 |
| --- | --- | --- |
{chr(10).join(rows)}

## Regenerate / 重新生成

```bash
python3 scripts/generate_markdown_review_index.py
```
"""
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
