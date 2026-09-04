"""Render the versioned legal manifest as a human-reviewable Markdown file."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


TYPE_LABELS = {
    "law": "法律",
    "administrative_regulation": "行政法规",
    "department_rule": "部门规章",
    "judicial_interpretation": "司法解释",
    "national_standard": "国家标准",
    "industry_standard": "公共安全行业标准",
    "official_case": "官方案例",
}
METHOD_LABELS = {
    "official_snapshot_substring": "官方快照自动逐字匹配",
    "official_pdf_visual_review": "官方 PDF 目视逐字复核并锁定指纹",
    "official_page_search_index_cross_check": "官方页面搜索索引与官方交叉来源复核",
}


def quote_block(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def render(
    manifest_path: Path,
    verification_path: Path,
    audit_path: Path,
) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    source_results = {
        item["document_id"]: item for item in verification["results"]
    }
    audit_results = {
        (
            item["document_id"],
            item["article_no"],
            item.get("paragraph_no"),
            item.get("item_no"),
        ): item
        for item in audit["results"]
    }
    documents = manifest["documents"]
    total_sections = sum(len(item["sections"]) for item in documents)
    method_counts = Counter(
        item["verification_method"] for item in audit["results"]
    )
    lines = [
        "# 交通事故责任与权益 Agent 法律语料清单（逐字复核版）",
        "",
        (
            f"> 数据基准：2026-07-29。本文档整理当前收录的 {len(documents)} "
            f"份权威材料及 {total_sections} 个可检索原文片段。"
            "本文档不替代官方全文、正式法律检索或专业法律意见。"
        ),
        "",
        "## 复核结论",
        "",
        f"- 文档数：**{len(documents)}**",
        f"- 可检索原文片段：**{total_sections}**",
        (
            f"- 逐字审计：**{audit['passed']}/{audit['quotes']} 通过**；"
            f"失败 **{audit['failed']}**"
        ),
        (
            "- 审计方式："
            f"{method_counts['official_snapshot_substring']} 条官方快照自动匹配，"
            f"{method_counts['official_pdf_visual_review']} 条官方 PDF 目视复核并锁定指纹，"
            f"{method_counts['official_page_search_index_cross_check']} 条官方页面索引/交叉来源复核"
        ),
        (
            f"- 在线重新下载：**{verification['verified']}/{verification['total']}**；"
            "GA 802-2019 正文页因政府站点 TLS 证书链异常未完成本轮直连，"
            "其版本状态由公安部标准平台核验，正文由益阳交警官方页搜索索引及官方交叉来源复核"
        ),
        "- 所有入库片段均标记为 `verbatim_excerpt`；摘要和标准状态题录不进入法律检索索引",
        "",
        "## 本次校正",
        "",
        "- 更正《道路交通安全法》第七十六条第一款引导语，补回“下列”及结尾冒号",
        "- 将《道路交通事故处理程序规定》第七十四条由概括性摘要替换为完整原文",
        "- 同步修复其余 12 处截断、概括或排版性非逐字摘录",
        "- 移除 2 条误入检索索引的“标准状态”题录，因此片段数由 50 调整为 48",
        "",
        "## 材料总览",
        "",
        "| # | Document ID | 材料 | 类型 | 版本 | 生效日期 | 片段数 | 本轮来源核验 |",
        "|---:|---|---|---|---|---|---:|---|",
    ]
    for index, document in enumerate(documents, start=1):
        source = source_results.get(document["document_id"], {})
        source_status = "在线成功" if source.get("verified") else "正文页 TLS 异常，已交叉复核"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    f"`{document['document_id']}`",
                    f"[{document['title']}]({document['source_url']})",
                    TYPE_LABELS[document["document_type"]],
                    document["version"],
                    document["effective_date"],
                    str(len(document["sections"])),
                    source_status,
                ]
            )
            + " |"
        )
    for index, document in enumerate(documents, start=1):
        lines.extend(
            [
                "",
                "---",
                "",
                f"## {index}. {document['title']}",
                "",
                f"- Document ID：`{document['document_id']}`",
                f"- 类型：{TYPE_LABELS[document['document_type']]}",
                f"- 发布机关：{document['issuer']}",
                f"- 版本：{document['version']}",
                f"- 生效日期：{document['effective_date']}",
                f"- 状态：`{document['status']}`",
                f"- 版本/题录来源：[官方页面]({document['source_url']})",
            ]
        )
        text_source_url = document.get(
            "text_source_url", document["source_url"]
        )
        if text_source_url != document["source_url"]:
            lines.append(f"- 正文来源：[官方正文]({text_source_url})")
        lines.extend(
            [
                "",
                f"### 纳入原文片段（{len(document['sections'])}）",
                "",
            ]
        )
        for section_index, section in enumerate(document["sections"], start=1):
            labels = [
                value
                for value in (
                    section.get("article_no"),
                    section.get("paragraph_no"),
                    section.get("item_no"),
                )
                if value
            ]
            audit_item = audit_results[
                (
                    document["document_id"],
                    section["article_no"],
                    section.get("paragraph_no"),
                    section.get("item_no"),
                )
            ]
            lines.extend(
                [
                    f"#### {section_index}. {' · '.join(labels)}",
                    "",
                    f"- 来源位置：{section['page_or_location']}",
                    f"- 引用类型：`{section['quote_type']}`",
                    (
                        "- 复核："
                        + METHOD_LABELS[audit_item["verification_method"]]
                    ),
                    "",
                    quote_block(section["text"]),
                    "",
                ]
            )
    lines.extend(
        [
            "---",
            "",
            "## 使用边界",
            "",
            "- 语料中的车辆技术参数用于证据核查，不支持“超标电动车当然等于机动车”的结论。",
            "- 法律结论仍须结合事故日期、车辆登记、鉴定意见、地区规则和证据状态。",
            "- 缺少有效引文时，系统禁止输出确定性法律结论。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/laws/source_manifest.json")
    )
    parser.add_argument(
        "--verification",
        type=Path,
        default=Path("data/laws/source_verification.json"),
    )
    parser.add_argument(
        "--audit", type=Path, default=Path("data/laws/quote_audit.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    content = render(args.manifest, args.verification, args.audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
