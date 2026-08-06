"""Generate a synthetic, local-only SFT corpus for ClaimCourt behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SYSTEM = (
    "You are ClaimCourt, a private local evidence and file-location agent. "
    "Return valid JSON only. Never invent citations. Never reveal a secret value; "
    "return a redacted preview and a fingerprint instead."
)


def record(user: str, assistant: dict[str, object]) -> dict[str, object]:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant, separators=(",", ":"))},
        ]
    }


def build_records() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    vendors = ["Atlas", "Brightline", "Cobalt", "Delta", "Evergreen", "Fjord"]
    commitments = ["99.9% uptime", "four-hour response", "a fixed delivery date"]
    for index in range(72):
        vendor = vendors[index % len(vendors)]
        commitment = commitments[index % len(commitments)]
        mode = index % 3
        if mode == 0:
            evidence = f"[ORDER-{index:02d}] Signed order form: {vendor} shall provide {commitment}."
            verdict = "supported"
            reason = "A signed order form directly states the commitment."
            citations = [f"ORDER-{index:02d}"]
            missing = []
        elif mode == 1:
            evidence = (
                f"[MSA-{index:02d}] The agreement creates no service level commitment unless a separately signed addendum exists.\n"
                f"[EMAIL-{index:02d}] Sales wrote: enterprise-grade reliability."
            )
            verdict = "contradicted"
            reason = "The binding agreement rejects an SLA while the email is non-binding marketing."
            citations = [f"MSA-{index:02d}", f"EMAIL-{index:02d}"]
            missing = ["A signed addendum or order form"]
        else:
            evidence = (
                f"[NOTES-{index:02d}] We target {commitment} after Q4, subject to capacity.\n"
                f"[EMAIL-{index:02d}] Sales described the service as reliable."
            )
            verdict = "insufficient_evidence"
            reason = "A conditional target and marketing language do not establish a binding commitment."
            citations = [f"NOTES-{index:02d}", f"EMAIL-{index:02d}"]
            missing = ["A signed contractual commitment"]
        rows.append(
            record(
                f"Decide whether {vendor} committed to {commitment}. Evidence packet:\n{evidence}",
                {
                    "route": "evidence_court",
                    "claim": f"{vendor} committed to {commitment}",
                    "verdict": verdict,
                    "confidence": 0.86,
                    "evidence_citations": citations,
                    "reasoning": reason,
                    "missing_evidence": missing,
                    "recommended_next_action": "Request the controlling signed record." if missing else "Use the signed order form in the decision brief.",
                },
            )
        )

    route_examples = [
        ("Find the slide deck about our pricing proposal.", "file_locator", ["pptx", "pdf"], False),
        ("Where did I leave a private key?", "sensitive_record_scan", ["all"], False),
        ("Did the customer approve the delay?", "evidence_court", ["email", "docx", "pdf"], False),
        ("Locate the meeting notes that mention Project Northstar.", "file_locator", ["md", "docx", "txt"], False),
        ("Search for API credentials in this workspace.", "sensitive_record_scan", ["all"], False),
        ("Create a brief explaining who approved the change request.", "evidence_court", ["email", "pdf", "docx"], True),
    ]
    for index in range(54):
        query, route, file_types, export_requested = route_examples[index % len(route_examples)]
        topics = [
            term for term in ("pricing", "private_key", "approval", "northstar", "credential", "change_request")
            if term.replace("_", " ") in query.lower() or term == "private_key" and "private key" in query.lower()
        ]
        rows.append(
            record(
                query,
                {
                    "intent": "evidence_question" if route == "evidence_court" else route,
                    "artifact_types": [f".{item}" if item != "all" and not item.startswith(".") else item for item in file_types],
                    "topics": topics,
                    "entities": ["Northstar"] if "Northstar" in query else [],
                    "time_hints": [],
                    "expanded_terms": topics,
                    "search_scope": ["file_name", "title", "full_text", "related_documents"] if route == "file_locator" else ["full_text", "page_or_slide", "related_documents"],
                    "relations": [],
                    "clarification_needed": False,
                    "clarification_question": "",
                    "confidence": 0.9,
                },
            )
        )

    for index in range(36):
        token = f"DEMO_CREDENTIAL_{index:02d}_NOT_A_REAL_SECRET"
        rows.append(
            record(
                f"A local scan found `{token}` in secrets/notes-{index:02d}.txt on line 4. Report it safely.",
                {
                    "route": "sensitive_record_scan",
                    "findings": [
                        {
                            "source": f"secrets/notes-{index:02d}.txt",
                            "locator": "line 4",
                            "kind": "synthetic credential",
                            "fingerprint": f"sha256:example{index:02d}fingerprint",
                            "redacted_preview": "DEMO_...[REDACTED]",
                        }
                    ],
                    "raw_secret_disclosed": False,
                    "recommended_next_action": "Revoke or rotate the credential and remove it from the workspace.",
                },
            )
        )

    fuzzy_cases = [
        (
            "我记得去年写过一份操作系统实验报告，里面有进程调度和虚拟内存",
            {"intent": "locate_artifact", "artifact_types": [".docx", ".pdf", ".md"], "topics": ["operating_system", "process_scheduling", "virtual_memory"], "time_hints": ["historical"], "relations": [], "clarification_needed": False, "confidence": 0.92},
        ),
        (
            "找一下客户延期之后我做的那个 Q4 风险 PPT",
            {"intent": "locate_artifact", "artifact_types": [".pptx", ".pdf"], "topics": ["customer_delay", "launch_risk"], "time_hints": ["Q4"], "relations": ["causal_after"], "clarification_needed": False, "confidence": 0.91},
        ),
        (
            "I cannot remember the filename, but it was the deck about the delayed customer launch",
            {"intent": "locate_artifact", "artifact_types": [".pptx", ".pdf"], "topics": ["customer_delay", "launch"], "time_hints": [], "relations": [], "clarification_needed": False, "confidence": 0.87},
        ),
        (
            "帮我找关于售后支持例外的那份已经签字的补充协议",
            {"intent": "locate_artifact", "artifact_types": [".pdf", ".docx", ".md"], "topics": ["support", "exception", "signed_addendum"], "time_hints": [], "relations": [], "clarification_needed": False, "confidence": 0.9},
        ),
        (
            "会议里谁批准了迁移顺序？不是找合同，是找批准记录",
            {"intent": "evidence_question", "artifact_types": [".md", ".eml", ".docx"], "topics": ["migration", "approval"], "time_hints": [], "relations": [], "clarification_needed": False, "confidence": 0.9},
        ),
        (
            "那个包含页面置换和文件系统分析的课程实验",
            {"intent": "locate_artifact", "artifact_types": [".docx", ".pdf", ".md"], "topics": ["operating_system", "virtual_memory", "file_system"], "time_hints": [], "relations": [], "clarification_needed": False, "confidence": 0.84},
        ),
        (
            "我只记得它讲客户变更和 Q4 交付风险，帮我找那份演示文稿",
            {"intent": "locate_artifact", "artifact_types": [".pptx", ".pdf"], "topics": ["customer_change", "delivery_risk"], "time_hints": ["Q4"], "relations": [], "clarification_needed": False, "confidence": 0.9},
        ),
        (
            "I remember a migration runbook with rollback steps, find it",
            {"intent": "locate_artifact", "artifact_types": [".md", ".docx", ".pdf"], "topics": ["migration", "runbook", "rollback"], "time_hints": [], "relations": [], "clarification_needed": False, "confidence": 0.88},
        ),
        (
            "帮我找 USA 服务器宝塔面板的账号密码，只给位置不要显示值",
            {"intent": "sensitive_record_scan", "artifact_types": ["all"], "topics": ["server", "baota", "credential"], "time_hints": [], "relations": [], "clarification_needed": False, "confidence": 0.98},
        ),
        (
            "帮我找一下那个报告",
            {"intent": "locate_artifact", "artifact_types": ["all"], "topics": [], "time_hints": [], "relations": [], "clarification_needed": True, "confidence": 0.38},
        ),
    ]
    for query, intent_plan in fuzzy_cases:
        topics = list(intent_plan["topics"])
        search_scope = (
            ["file_name", "title", "full_text", "related_documents"]
            if intent_plan["intent"] == "locate_artifact"
            else ["full_text", "page_or_slide", "related_documents"]
        )
        rows.append(
            record(
                query,
                {
                    "intent": intent_plan["intent"],
                    "artifact_types": intent_plan["artifact_types"],
                    "topics": topics,
                    "entities": [],
                    "time_hints": intent_plan["time_hints"],
                    "expanded_terms": topics,
                    "search_scope": search_scope,
                    "relations": intent_plan["relations"],
                    "clarification_needed": intent_plan["clarification_needed"],
                    "clarification_question": "你还记得主题、时间、格式或正文关键词吗？" if intent_plan["clarification_needed"] else "",
                    "confidence": intent_plan["confidence"],
                },
            )
        )
    return rows


def intent_record(
    query: str,
    *,
    intent: str,
    artifact_types: list[str],
    topics: list[str],
    entities: list[str] | None = None,
    time_hints: list[str] | None = None,
    expanded_terms: list[str] | None = None,
    relations: list[str] | None = None,
    clarification_needed: bool = False,
    confidence: float = 0.9,
) -> dict[str, object]:
    search_scope = (
        ["file_name", "title", "full_text", "related_documents"]
        if intent == "locate_artifact"
        else ["full_text", "page_or_slide", "related_documents"]
    )
    return record(
        query,
        {
            "intent": intent,
            "artifact_types": artifact_types,
            "topics": topics,
            "entities": entities or [],
            "time_hints": time_hints or [],
            "expanded_terms": expanded_terms or topics,
            "search_scope": search_scope,
            "relations": relations or [],
            "clarification_needed": clarification_needed,
            "clarification_question": (
                "你还记得主题、时间、格式或正文关键词吗？"
                if clarification_needed and any("\u4e00" <= char <= "\u9fff" for char in query)
                else "Do you remember its topic, approximate date, format, or a phrase inside it?"
                if clarification_needed
                else ""
            ),
            "confidence": confidence,
        },
    )


def build_intent_records() -> list[dict[str, object]]:
    """Build diverse query-only SFT data without using private workspace text."""

    scenarios = [
        ("操作系统线程实验", "operating-systems threading lab", ["operating_system", "threading"], ["thread", "线程", "多线程"], [".doc", ".docx", ".pdf"]),
        ("页面置换算法报告", "page-replacement simulation report", ["operating_system", "page_replacement"], ["FIFO", "LRU", "页面置换"], [".doc", ".docx", ".pdf"]),
        ("磁盘调度实验", "disk-scheduling experiment", ["operating_system", "disk_scheduling"], ["SSTF", "移动臂调度"], [".doc", ".docx", ".pdf"]),
        ("文件读写实验", "file-operations lab", ["operating_system", "file_operations"], ["文件读写", "file operations"], [".doc", ".docx", ".pdf"]),
        ("数据库第二次实验", "second database lab", ["database"], ["数据库", "SQL", "实验二"], [".doc", ".docx", ".pdf"]),
        ("单周期 CPU 设计", "single-cycle CPU design", ["computer_organization"], ["CPU", "单周期", "计算机组成原理"], [".doc", ".docx", ".pdf"]),
        ("Verilog 快速入门课件", "Verilog quick-start slides", ["digital_logic"], ["Verilog", "数字逻辑"], [".pptx", ".pdf"]),
        ("ARM 第三份实验", "third ARM experiment", ["embedded_arm"], ["ARM", "嵌入式", "第三份"], [".doc", ".docx", ".pdf"]),
        ("象棋 AI 框架设计", "chess AI architecture", ["chess_ai"], ["MCTS", "policy-value network", "象棋"], [".doc", ".docx", ".pdf"]),
        ("敦煌古韵演示文稿", "Dunhuang culture presentation", ["dunhuang"], ["敦煌", "Dunhuang"], [".pptx", ".pdf"]),
        ("职业生涯规划 PPT", "career-planning deck", ["career_planning"], ["职业规划", "career planning"], [".pptx", ".pdf"]),
        ("计量分析报告", "econometrics analysis report", ["econometrics"], ["描述性统计", "econometrics"], [".doc", ".docx", ".pdf"]),
        ("客户延期后的 Q4 风险演示", "Q4 risk deck after the customer delay", ["delay", "risk", "delivery"], ["Q4", "延期", "delivery risk"], [".pptx", ".pdf"]),
        ("已签署的支持补充协议", "signed support addendum", ["support", "signed_addendum"], ["signed", "支持例外", "补充协议"], [".doc", ".docx", ".pdf"]),
        ("带回滚步骤的迁移手册", "migration runbook with rollback steps", ["migration", "runbook"], ["rollback", "迁移", "回滚"], [".md", ".docx", ".pdf"]),
        ("计算机网络报告模板", "computer-network report template", ["computer_network", "coursework"], ["计算机网络", "template", "模板"], [".doc", ".docx", ".pdf"]),
    ]
    zh_templates = [
        "我以前写过一份{subject}，文件名记不清了，帮我找出来",
        "找一下那个{subject}，应该是正式版，不要模板或备份",
        "我只记得内容和{subject}有关，可能是老的 Word 文档",
        "把{subject}找出来，并告诉我它在哪个目录",
        "之前做过{subject}，名字可能不是主题开头",
        "寻找{subject}，不要把试卷、答案或副本排在前面",
    ]
    en_templates = [
        "Find the {subject}; I cannot remember the filename.",
        "Locate my {subject}, not a template, backup, or exam answer.",
        "I remember making a {subject}; retrieve the most likely final file.",
        "Which local document contains the {subject}?",
    ]
    rows: list[dict[str, object]] = []
    for index, (zh, en, topics, expansions, types) in enumerate(scenarios):
        for template in zh_templates:
            rows.append(
                intent_record(
                    template.format(subject=zh),
                    intent="locate_artifact",
                    artifact_types=types,
                    topics=topics,
                    time_hints=["historical"] if "以前" in template or "之前" in template else [],
                    expanded_terms=expansions,
                    confidence=0.88 + (index % 3) * 0.02,
                )
            )
        for template in en_templates:
            rows.append(
                intent_record(
                    template.format(subject=en),
                    intent="locate_artifact",
                    artifact_types=types,
                    topics=topics,
                    time_hints=["historical"] if "remember making" in template else [],
                    expanded_terms=expansions,
                    confidence=0.88 + (index % 3) * 0.02,
                )
            )

    relation_cases = [
        ("找客户延期之后制作的风险 PPT", ["delay", "risk"], ["causal_after"], [".pptx", ".pdf"]),
        ("找批准迁移之前的会议纪要", ["approval", "migration"], ["temporal_before"], [".md", ".docx", ".eml"]),
        ("Locate the deck created after Project Northstar slipped.", ["delay", "risk"], ["causal_after"], [".pptx", ".pdf"]),
        ("Find the approval record preceding the production cutover.", ["approval", "migration"], ["temporal_before"], [".md", ".docx", ".eml"]),
    ]
    for query, topics, relations, types in relation_cases:
        for suffix in ("", " 文件名我不记得了" if any("\u4e00" <= char <= "\u9fff" for char in query) else " I forgot the filename."):
            rows.append(intent_record(query + suffix, intent="locate_artifact", artifact_types=types, topics=topics, relations=relations))

    sensitive_queries = [
        "扫描本地代码里的密码和 API key，只返回位置和遮罩预览",
        "查找服务器面板账号密码，但绝不能显示秘密值",
        "检查笔记中的私钥、Token 或凭证并给出指纹",
        "排查配置文件有没有遗留密钥，只报告风险类别",
        "Scan local files for credentials and return only masked fingerprints.",
        "Audit source code for API keys without revealing any secret value.",
        "Find where a private key is stored; report the path, never the key.",
        "Check configuration notes for passwords and redact every value.",
    ]
    zh_scan_scopes = ["", "递归检查子目录", "包含旧备份目录", "检查代码和配置", "覆盖笔记与脚本", "只输出文件与行号"]
    en_scan_scopes = ["", "Include nested folders.", "Include old backup folders.", "Inspect code and configuration.", "Cover notes and scripts.", "Return only files and line numbers."]
    for cycle in range(6):
        for query in sensitive_queries:
            is_chinese = any("\u4e00" <= char <= "\u9fff" for char in query)
            scope = zh_scan_scopes[cycle] if is_chinese else en_scan_scopes[cycle]
            rows.append(
                intent_record(
                    f"{query} {scope}".strip(),
                    intent="sensitive_record_scan",
                    artifact_types=["all"],
                    topics=["credential", "privacy"],
                    expanded_terms=["private key", "API key", "token", "password", "凭证", "密钥"],
                    confidence=0.98,
                )
            )

    evidence_queries = [
        ("供应商是否承诺了 99.9% 可用性？", ["reliability", "commitment"]),
        ("客户到底有没有批准延期？", ["approval", "delay"]),
        ("谁批准了需求变更，证据在哪里？", ["approval", "change_request"]),
        ("合同和销售邮件关于 SLA 是否矛盾？", ["reliability", "contradiction"]),
        ("Did the vendor contractually commit to 99.9% uptime?", ["reliability", "commitment"]),
        ("Who approved the change request, and what evidence supports it?", ["approval", "change_request"]),
        ("Did the customer agree to the delayed delivery date?", ["approval", "delay"]),
        ("Do the signed agreement and sales email contradict each other?", ["contradiction", "contract"]),
    ]
    zh_evidence_scopes = ["", "请只引用原始证据。", "同时列出反证。", "指出缺失的签署材料。", "按时间线解释。"]
    en_evidence_scopes = ["", "Cite only source evidence.", "Include contrary evidence.", "Identify missing signed records.", "Explain it as a timeline."]
    for cycle in range(5):
        for query, topics in evidence_queries:
            is_chinese = any("\u4e00" <= char <= "\u9fff" for char in query)
            scope = zh_evidence_scopes[cycle] if is_chinese else en_evidence_scopes[cycle]
            rows.append(
                intent_record(
                    f"{query} {scope}".strip(),
                    intent="evidence_question",
                    artifact_types=[".pdf", ".doc", ".docx", ".eml", ".md", ".txt"],
                    topics=topics,
                    confidence=0.94,
                )
            )

    vague_queries = [
        "帮我找以前写过的那个报告",
        "找一下那个实验，我不记得是什么课",
        "找我去年做的电脑课设",
        "我记得有一份文档，但主题和格式都忘了",
        "Find that report I wrote before.",
        "Locate the old experiment; I forgot the course and format.",
        "I made a document last year, but remember nothing else.",
        "Where is that file we discussed?",
    ]
    zh_vague_details = ["", "大概在桌面", "可能是旧文件", "格式也记不清了"]
    en_vague_details = ["", "Maybe on the desktop.", "It may be an older file.", "I also forgot the format."]
    for cycle in range(4):
        for query in vague_queries:
            is_chinese = any("\u4e00" <= char <= "\u9fff" for char in query)
            detail = zh_vague_details[cycle] if is_chinese else en_vague_details[cycle]
            rows.append(
                intent_record(
                    f"{query} {detail}".strip(),
                    intent="locate_artifact",
                    artifact_types=["all"],
                    topics=[],
                    clarification_needed=True,
                    confidence=0.32 + cycle * 0.02,
                )
            )

    serialized = [json.dumps(row, sort_keys=True) for row in rows]
    if len(serialized) != len(set(serialized)):
        raise ValueError("Synthetic intent corpus contains duplicate records")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("training/data/claimcourt_sft.jsonl"))
    parser.add_argument("--intent-output", type=Path, default=Path("training/data/claimcourt_intent_sft.jsonl"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = build_records()
    args.output.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    intent_rows = build_intent_records()
    args.intent_output.parent.mkdir(parents=True, exist_ok=True)
    args.intent_output.write_text("\n".join(json.dumps(row) for row in intent_rows) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} synthetic examples to {args.output}")
    print(f"Wrote {len(intent_rows)} fuzzy-intent examples to {args.intent_output}")


if __name__ == "__main__":
    main()
