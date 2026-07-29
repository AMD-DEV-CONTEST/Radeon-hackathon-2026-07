"""Generate ~10k related private-enterprise FAQs for Track 2 RAG demo."""

from __future__ import annotations

import argparse
from pathlib import Path

# Topic banks stay in the private-agent / company-IT domain so retrieval stays relevant.
CATEGORIES: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "vpn_network",
        [
            ("如何重置 {sys} 密码？", "打开内部门户 → Security → Reset {sys} Password，完成 MFA 后生效，约 5 分钟同步。"),
            ("{sys} 连不上怎么办？", "检查公司网络/代理，确认 MFA 未过期；仍失败请在 ServiceDesk 提「网络/{sys}」工单。"),
            ("出差时能否使用 {sys}？", "可以。使用公司笔记本 + 最新 {sys} 客户端，禁止在公共电脑保存证书。"),
            ("{sys} 多设备限制是多少？", "同一账号最多同时在线 {n} 台设备，超出需先在门户注销旧会话。"),
            ("谁有权审批 {sys} 特权访问？", "直属经理 + IT Security。审批 SLA 为 {n} 个工作日。"),
        ],
    ),
    (
        "ai_compliance",
        [
            ("涉密内容可以用哪些 AI 工具？", "仅允许 PrivateLocalAgent 及公司批准的本地模型；禁止粘贴到公网聊天机器人。"),
            ("能否把 {doc} 上传到公网大模型？", "不可以。{doc} 属于受控数据，只能在私有知识库 / 本地 Agent 内处理。"),
            ("PrivateLocalAgent 适合做什么？", "私有知识检索、内部政策问答、本地工具调用；不用于对外公开发布未经审核的内容。"),
            ("Track 2 私有 Agent 是否必须本地推理？", "是。优先 AMD Radeon GPU + ROCm 本地推理，敏感负载不走公网 API。"),
            ("模型输出能否直接当正式制度？", "不能。Agent 回答需人工复核后再作为正式通知或制度发布。"),
        ],
    ),
    (
        "hr_leave",
        [
            ("请假需要提前几天申请？", "年假须至少提前 {n} 个工作日在 HR 系统提交；紧急事假当日补单并说明原因。"),
            ("试用期年假有几天？", "试用期按公司政策折算；转正后标准年假为 {n} 天（满 3 年后 15 天）。"),
            ("病假超过一天要什么材料？", "需提供医疗机构证明；全年带薪病假上限 {n} 天。"),
            ("远程办公一周最多几天？", "经理批准下最多 {n} 天/周；涉密客户数据须留在私有工作区。"),
            ("请假超过三天谁审批？", "直属经理 + HR；三天及以内仅需直属经理。"),
        ],
    ),
    (
        "software_license",
        [
            ("如何申请 {soft} 许可证？", "在 ServiceDesk 提单工单，填写成本中心 ID；标准审批 SLA {n} 个工作日。"),
            ("个人版 {soft} 能用于项目吗？", "不可以。项目须使用公司采购的企业许可，个人版禁止处理公司代码/数据。"),
            ("许可证到期怎么办？", "到期前 {n} 天门户会提醒；续订走 ServiceDesk「License Renewal」。"),
            ("开源组件商用要注意什么？", "引入前在合规清单登记许可证类型；Copyleft 组件需法务评审。"),
            ("闲置许可证如何回收？", "停用账号后 IT 资产组在 {n} 个工作日内回收席位。"),
        ],
    ),
    (
        "docs_kb",
        [
            ("项目设计文档放在哪里？", "私有知识库 `Projects/Design`，按角色授权；禁止同步到个人网盘。"),
            ("如何更新知识库中的 {doc}？", "在私有目录提交变更，经负责人审核后重新 ingest 到向量库。"),
            ("知识库检索不到怎么办？", "确认文档已入库、关键词与文档语言一致；仍失败联系知识库管理员重建索引。"),
            ("谁可以导出完整知识库？", "仅知识库管理员；普通用户只能通过 PrivateLocalAgent 检索片段。"),
            ("会议纪要模板在哪？", "见 sample_docs/meeting_notes_template.md，复制后按项目目录归档。"),
        ],
    ),
    (
        "gpu_rocm",
        [
            ("GPU 推理环境有什么要求？", "Track 2 使用 AMD Radeon GPU + ROCm；私有负载优先本地推理。"),
            ("ROCm 驱动异常怎么排查？", "先跑 `rocm-smi` 确认设备可见；驱动/容器版本不匹配时提 IT「ROCm」工单。"),
            ("本地模型 OOM 怎么办？", "换更小模型（如 1.5B）、降低 max_tokens，或清理其他占用显存的进程。"),
            ("能否在共享 GPU 节点跑涉密任务？", "仅限隔离的私有实例/PVC；禁止把密钥写进公共镜像层。"),
            ("embedding 模型用哪个？", "默认 `sentence-transformers/all-MiniLM-L6-v2`，可按配置切换，须本地缓存。"),
        ],
    ),
    (
        "security_access",
        [
            ("如何申请 {sys} 权限？", "ServiceDesk 选择 Access Request，经理审批后 IT 开通，默认只读。"),
            ("账号被锁定怎么解锁？", "连续失败 {n} 次会锁定；门户自助解锁或联系 IT Security。"),
            ("U 盘拷贝源代码允许吗？", "默认禁止。例外须安全组书面批准并登记资产编号。"),
            ("发现可疑钓鱼邮件怎么做？", "不要点击链接；转发至 security@company.example 并删除原邮件。"),
            ("离职当天权限何时收回？", "HR 确认后 IT 在当天关闭 SSO/{sys}；共享盘权限同步失效。"),
        ],
    ),
    (
        "servicedesk_ops",
        [
            ("ServiceDesk 标准响应时间？", "P3 普通请求 {n} 个工作日；P1 生产中断 1 小时内响应。"),
            ("如何升级紧急工单？", "在工单内点 Escalate，并电话通知值班（门户「On-call」）。"),
            ("忘记公司邮箱密码？", "门户自助重置；若 MFA 设备丢失，携带工牌到 IT 前台核验。"),
            ("新员工入职 IT 清单？", "开通账号、VPN、知识库只读、笔记本；第 {n} 天完成安全培训。"),
            ("打印机驱动在哪下载？", "内网 Software Center → Printers；禁止安装来路不明驱动。"),
        ],
    ),
    (
        "data_privacy",
        [
            ("客户名单能否发到微信？", "不可以。客户与合同数据仅限公司邮箱/私有系统传输。"),
            ("日志里能否存明文密码？", "严禁。日志需脱敏；发现明文立即报安全事件。"),
            ("本地磁盘加密要求？", "公司笔记本必须开启全盘加密；丢失立即报 IT Security。"),
            ("第三方供应商要数据怎么审批？", "走 DPA 流程：业务负责人 + 法务 + 安全三方签字。"),
            ("备份保留多久？", "业务数据默认保留 {n} 天；合规类按法规单独策略。"),
        ],
    ),
    (
        "dev_process",
        [
            ("代码仓库权限如何申请？", "在 Git 门户申请加入项目组，Maintainer 审批后生效。"),
            ("合并请求需要几人审核？", "至少 {n} 名 Reviewer；涉及安全配置须安全组加审。"),
            ("CI 失败能否强制合并？", "不可以。须修复或获得 Tech Lead 书面豁免。"),
            ("私有 Agent 演示推荐方式？", "优先 Jupyter Notebook / CLI；公网隧道不稳定时不要依赖网页代理。"),
            ("Hackathon 提交前检查什么？", "Fork+Star、Track2 分支、可运行 demo、README/清单、录屏。"),
        ],
    ),
]

SYSTEMS = ["VPN", "SSO", "Git", "Jira", "Confluence", "LDAP", "ZeroTrust", "WiFi门户"]
DOCS = ["设计文档", "客户合同", "薪资表", "源代码", "会议纪要", "安全审计报告", "模型权重清单"]
SOFTS = ["IDE", "Office", "绘图工具", "数据库客户端", "容器桌面", "API 调试器", "设计协作软件"]
NS = [1, 2, 3, 5, 7, 10, 15]


def _fill(template: str, i: int) -> str:
    return (
        template.replace("{sys}", SYSTEMS[i % len(SYSTEMS)])
        .replace("{doc}", DOCS[i % len(DOCS)])
        .replace("{soft}", SOFTS[i % len(SOFTS)])
        .replace("{n}", str(NS[i % len(NS)]))
    )


def generate(n: int, out_dir: Path, per_file: int = 200) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    # wipe previous generated set
    for old in out_dir.glob("faq_batch_*.md"):
        old.unlink()

    templates: list[tuple[str, str, str]] = []
    for cat, pairs in CATEGORIES:
        for q, a in pairs:
            templates.append((cat, q, a))

    written = 0
    batch: list[str] = []
    file_idx = 0

    def flush() -> None:
        nonlocal file_idx, batch
        if not batch:
            return
        file_idx += 1
        path = out_dir / f"faq_batch_{file_idx:03d}.md"
        header = f"# 私有企业 FAQ 批次 {file_idx}\n\n> 与 IT / HR / 安全 / ROCm / PrivateLocalAgent 相关\n\n"
        path.write_text(header + "\n".join(batch), encoding="utf-8")
        batch = []

    i = 0
    while written < n:
        cat, q_t, a_t = templates[i % len(templates)]
        q = _fill(q_t, i)
        a = _fill(a_t, i)
        # slight paraphrase index so near-duplicates stay searchable as variants
        qid = written + 1
        batch.append(f"## Q{qid}（{cat}）：{q}\n{a}\n")
        written += 1
        i += 1
        if len(batch) >= per_file:
            flush()

    flush()
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10000)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "sample_docs" / "faq_10k",
    )
    parser.add_argument("--per-file", type=int, default=200)
    args = parser.parse_args()
    count = generate(args.n, args.out, args.per_file)
    print(f"generated {count} FAQs -> {args.out}")


if __name__ == "__main__":
    main()
