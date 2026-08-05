"""
Report Generator — 使用本地 LLM 生成管理层摘要。
运行在 AMD Radeon GPU + ROCm 上，通过 OpenAI 兼容接口调用 vLLM/llama.cpp。
"""

import json
from pathlib import Path
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


# 管理层报告提示词（中文）
REPORT_PROMPT = """你是一位资深供应链库存管理专家。请根据以下盘点差异分析数据，生成一份面向管理层的中文摘要报告。

**重要规则**：
1. 所有结论必须严格基于下方提供的分析数据，不得编造或推测未提供的信息。
2. 所有 SKU 只能来自 Top-5 差异 SKU 表格。不得补充、猜测或编造任何未提供的 SKU。
3. 事实计算由确定性 pandas 工作流完成，LLM 仅做报告表达。

## 分析数据摘要

### 基本概况
- SKU 总数：{total_sku} 个
- 系统库存：{system_total:,} 件
- 复盘总数：{recount_total:,} 件
- 净差异：{net_variance:,} 件
- 差异率：{variance_rate}%
- 净差异金额：{net_variance_amount:,.2f} 元

### 差异分布
- 盘亏 SKU：{loss_count} 个，盘亏金额：{total_loss_amount:,.2f} 元
- 盘盈 SKU：{gain_count} 个，盘盈金额：{total_gain_amount:,.2f} 元

### 噪音数据处理
- 扫描日志总记录：{scan_total} 条
- 噪音记录（已排除）：{noise_count} 条（{noise_ratio:.1f}%）
- 历史异常记录：{history_anomalies} 条

### 日志关联分析
- 完全可解释：{fully_explained} 个 SKU（金额 {fully_explained_amount:,.2f} 元）
- 部分可解释：{partially_explained} 个 SKU（金额 {partially_explained_amount:,.2f} 元）
- 无日志关联：{no_log} 个 SKU（金额 {no_log_amount:,.2f} 元）

### 品类异常（差异率 > 5%）
{category_anomalies}

### Top-5 差异 SKU
{top5_sku_table}

### 质量门禁摘要
{quality_gate_summary}

### 运行元数据
- run_id: {run_id}
- workflow_version: {workflow_version}
- input_file_count: {input_file_count}
- workflow_duration: {workflow_duration}

### 调账材料包
{deliverable_package_list}

### 处置建议
{disposition_recommendations_table}

### 数据边界
{data_boundary_declaration}

### 质量校验
{quality_checks}

## 请生成以下内容：

### 1. 管理层摘要（2-3 段话）
用简洁的语言概括本次盘点的核心发现，适合非技术背景的管理层阅读。

### 2. 风险分级
对以下维度进行高/中/低风险分级，并说明理由：
- 整体库存准确性
- 高价值品类风险
- 流程合规性

### 3. Top-5 异常 SKU 解读
列出差异金额最大的 5 个 SKU 并分析可能原因（仅使用上方 Top-5 差异 SKU 表格中的数据）。

### 4. 处置建议
基于上方处置建议表格，说明各分类的后续行动。

### 5. 下一步行动建议
给出 3-5 条具体可执行的改进建议。

### 6. 人审边界
说明 Agent 输出建议，调账执行需由仓库 / 财务 / 审计人员复核确认。

请用 Markdown 格式输出。"""


# 管理层报告提示词（英文）
REPORT_PROMPT_EN = """You are a senior supply chain inventory management expert. Based on the following inventory counting variance analysis data, generate an executive summary report in English.

**Important rules**:
1. All conclusions must be strictly based on the analysis data provided below. Do not fabricate or speculate on information not provided.
2. All SKUs must come only from the Top-5 Variance SKU table. Do not supplement, guess, or fabricate any SKUs not provided.
3. Factual computation is performed by a deterministic pandas workflow. LLM only handles report expression.

## Analysis Data Summary

### Basic Overview
- Total SKUs: {total_sku}
- System Stock: {system_total:,} pcs
- Recount Total: {recount_total:,} pcs
- Net Variance: {net_variance:,} pcs
- Variance Rate: {variance_rate}%
- Net Variance Amount: {net_variance_amount:,.2f} CNY

### Variance Distribution
- Shortage SKUs: {loss_count}, Shortage Amount: {total_loss_amount:,.2f} CNY
- Surplus SKUs: {gain_count}, Surplus Amount: {total_gain_amount:,.2f} CNY

### Noise Data Processing
- Total scan log records: {scan_total}
- Noise records (excluded): {noise_count} ({noise_ratio:.1f}%)
- Historical anomalies: {history_anomalies}

### Log Correlation Analysis
- Fully Explained: {fully_explained} SKUs (Amount {fully_explained_amount:,.2f} CNY)
- Partially Explained: {partially_explained} SKUs (Amount {partially_explained_amount:,.2f} CNY)
- No Log Correlation: {no_log} SKUs (Amount {no_log_amount:,.2f} CNY)

### Category Anomalies (Variance Rate > 5%)
{category_anomalies}

### Top-5 Variance SKUs
{top5_sku_table}

### Quality Gate Summary
{quality_gate_summary}

### Run Metadata
- run_id: {run_id}
- workflow_version: {workflow_version}
- input_file_count: {input_file_count}
- workflow_duration: {workflow_duration}

### Deliverable Package
{deliverable_package_list}

### Disposition Recommendations
{disposition_recommendations_table}

### Data Boundary
{data_boundary_declaration}

### Quality Checks
{quality_checks}

## Please generate the following:

### 1. Executive Summary (2-3 paragraphs)
Concise language summarizing the core findings of this inventory count, suitable for non-technical management.

### 2. Risk Grading
Assign High/Medium/Low risk levels to the following dimensions with rationale:
- Overall inventory accuracy
- High-value category risk
- Process compliance

### 3. Top-5 Variance SKU Analysis
List the top 5 SKUs by variance amount and analyze possible causes (use only data from the Top-5 Variance SKU table above).

### 4. Disposition Recommendations
Based on the disposition recommendations table above, explain follow-up actions for each category.

### 5. Next Steps
Provide 3-5 specific, actionable improvement recommendations.

### 6. Human Review Boundary
State that Agent outputs recommendations, but adjustment execution must be reviewed and confirmed by warehouse/finance/audit personnel.

Please output in Markdown format."""


class ReportGenerator:
    """使用本地 LLM 生成管理层摘要报告。"""

    def __init__(self, config: dict):
        self.config = config
        self.llm = self._init_llm()

    def _init_llm(self) -> ChatOpenAI:
        """初始化 LLM 连接（vLLM 或 llama.cpp）。"""
        # 从配置或环境变量读取 LLM 服务地址
        import os
        base_url = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
        model = os.getenv("LLM_MODEL", self.config.get("model", {}).get("name", "meta-llama/Llama-3.1-8B-Instruct"))

        streaming = os.getenv("LLM_STREAMING", "true").lower() == "true"
        return ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key="not-needed",
            temperature=0.3,
            max_tokens=2048,
            streaming=streaming,
            timeout=10,
            max_retries=1,
        )

    def _extract_metrics(self, analysis_result: dict) -> dict:
        """从分析结果中提取关键指标。"""
        step5 = analysis_result.get("Step 5: 加载盘点结果", {})
        step6 = analysis_result.get("Step 6: 计算差异金额", {})
        step7 = analysis_result.get("Step 7: 日志关联分析", {})
        step9 = analysis_result.get("Step 9: 品类维度分析", {})
        quality = analysis_result.get("quality_checks", [])
        meta = analysis_result.get("_metadata", {})

        # 噪音数据（存储为 Python 字符串表示，包含 pandas Series 无法直接解析）
        step2_str = analysis_result.get("Step 2: 识别噪音数据", "{}")
        step2 = {}
        if isinstance(step2_str, dict):
            step2 = step2_str
        elif isinstance(step2_str, str):
            import re
            noise_count_match = re.search(r"'noise_count':\s*(\d+)", step2_str)
            real_count_match = re.search(r"'real_count':\s*(\d+)", step2_str)
            history_match = re.search(r"'total_anomalies':\s*(?:np\.int64\()?(\d+)", step2_str)

            scan_log_noise = {}
            if noise_count_match:
                scan_log_noise["noise_count"] = int(noise_count_match.group(1))
            if real_count_match:
                scan_log_noise["real_count"] = int(real_count_match.group(1))

            history_anomalies = {}
            if history_match:
                history_anomalies["total_anomalies"] = int(history_match.group(1))

            step2 = {
                "scan_log_noise": scan_log_noise,
                "history_anomalies": history_anomalies,
                "noise_files": [],
            }

        scan_log = step2.get("scan_log_noise", {})
        history = step2.get("history_anomalies", {})

        # 日志关联
        fully = step7.get("完全可解释", {})
        partial = step7.get("部分可解释", {})
        no_log = step7.get("无日志关联", {})

        # 品类异常
        anomaly_cats = step9.get("anomaly_categories", [])
        category_lines = []
        for cat in anomaly_cats:
            category_lines.append(f"- {cat['品类']}：差异率 {cat['差异率']}%，严重程度 {cat['严重程度']}")
        category_anomalies = "\n".join(category_lines) if category_lines else "无异常品类"

        # 质量校验
        check_lines = []
        for i, c in enumerate(quality, 1):
            status = "通过" if c.get("passed") else "未通过"
            check_lines.append(f"{i}. {c.get('name', '')} — {status}（{c.get('importance', '')}）")
        quality_text = "\n".join(check_lines) if check_lines else "无校验记录"

        # Top-5 SKU 表格（优先 _metadata，回退顶层）
        top_skus = meta.get("top_variance_skus", analysis_result.get("top_variance_skus", []))
        top5_lines = ["| 排名 | 型号 | 品类 | 系统库存 | 复盘 | 差异数量 | 差异金额 | 差异类型 |"]
        top5_lines.append("|---|---|---|---|---|---|---|---|")
        for s in top_skus:
            top5_lines.append(
                f"| {s['rank']} | {s['sku']} | {s.get('category', '')} | "
                f"{s.get('system_stock', 0)} | {s.get('recount_stock', 0)} | "
                f"{s.get('variance_qty', 0)} | {s.get('variance_amount', 0):,.2f} | "
                f"{s.get('variance_type', '')} |"
            )
        top5_sku_table = "\n".join(top5_lines) if top_skus else "无 Top-5 差异 SKU 数据"

        # 质量门禁摘要
        qg = meta.get("quality_gate", {})
        if qg:
            qg_lines = [
                f"- 通过: {qg.get('passed_count', 0)}/{qg.get('total', 0)}",
                f"- Critical 失败: {qg.get('critical_failed', 0)}",
                f"- Major 失败: {qg.get('major_failed', 0)}",
                f"- 报告生成: {'允许' if qg.get('report_allowed', True) else '阻断'}"
            ]
            quality_gate_summary = "\n".join(qg_lines)
        else:
            quality_gate_summary = "无质量门禁数据"

        # 调账材料包清单
        dp = meta.get("deliverable_package", {})
        if dp:
            dp_lines = []
            for key, info in dp.items():
                exists_mark = "✅" if info.get("exists") else "❌"
                dp_lines.append(f"- {exists_mark} **{key}**: {info.get('path', '')} — {info.get('purpose', '')}")
            deliverable_package_list = "\n".join(dp_lines)
        else:
            deliverable_package_list = "无调账材料包数据"

        # 处置建议表格
        disp_recs = analysis_result.get("disposition_recommendations", [])
        if disp_recs:
            disp_lines = ["| 类别 | 数量 | 负责人 | 时限 | 建议 |"]
            disp_lines.append("|---|---|---|---|---|")
            for r in disp_recs:
                disp_lines.append(
                    f"| {r.get('category', '')} | {r.get('related_count', 0)} | "
                    f"{r.get('owner_role', '')} | {r.get('time_limit', '')} | "
                    f"{r.get('recommendation', '')} |"
                )
            disposition_recommendations_table = "\n".join(disp_lines)
        else:
            disposition_recommendations_table = "无处置建议数据"

        # 运行元数据
        run_id = meta.get("run_id", analysis_result.get("run_id", "N/A"))
        workflow_version = meta.get("workflow_version", "10-step-v1")
        input_file_count = len(meta.get("input_files", []))
        duration = meta.get("duration_seconds", 0)
        workflow_duration = f"{duration:.3f} 秒" if duration else "N/A"

        # 配置元数据
        import os
        llm_base_url = os.getenv("LLM_BASE_URL", self.config.get("model", {}).get("base_url", "http://localhost:8000/v1"))
        llm_model = os.getenv("LLM_MODEL", self.config.get("model", {}).get("name", "N/A"))

        data_boundary_declaration = (
            "事实计算由确定性 pandas 工作流完成，LLM 仅做表达。"
            "数据全程在本地处理，不依赖外部 API 或云服务。"
        )
        human_review_boundary = (
            "Agent 输出建议，调账执行需由仓库 / 财务 / 审计人员复核确认。"
            "本报告不构成最终调账指令。"
        )

        return {
            "total_sku": step5.get("total_sku", 0),
            "system_total": step5.get("system_total", 0),
            "recount_total": step5.get("recount_total", 0),
            "net_variance": step5.get("net_variance", 0),
            "variance_rate": step5.get("variance_rate", 0),
            "loss_count": step5.get("loss_count", 0),
            "gain_count": step5.get("gain_count", 0),
            "net_variance_amount": step6.get("net_variance_amount", 0),
            "total_loss_amount": step6.get("total_loss_amount", 0),
            "total_gain_amount": step6.get("total_gain_amount", 0),
            "scan_total": scan_log.get("real_count", 0) + scan_log.get("noise_count", 0),
            "noise_count": scan_log.get("noise_count", 0),
            "noise_ratio": (scan_log.get("noise_count", 0) / max(scan_log.get("real_count", 0) + scan_log.get("noise_count", 0), 1)) * 100,
            "history_anomalies": history.get("total_anomalies", 0),
            "fully_explained": fully.get("count", 0),
            "fully_explained_amount": fully.get("amount", 0),
            "partially_explained": partial.get("count", 0),
            "partially_explained_amount": partial.get("amount", 0),
            "no_log": no_log.get("count", 0),
            "no_log_amount": no_log.get("amount", 0),
            "category_anomalies": category_anomalies,
            "quality_checks": quality_text,
            "top5_sku_table": top5_sku_table,
            "quality_gate_summary": quality_gate_summary,
            "quality_report_allowed": qg.get("report_allowed", True),
            "run_id": run_id,
            "input_file_count": input_file_count,
            "workflow_version": workflow_version,
            "workflow_duration": workflow_duration,
            "deliverable_package_list": deliverable_package_list,
            "disposition_recommendations_table": disposition_recommendations_table,
            "data_boundary_declaration": data_boundary_declaration,
            "human_review_boundary": human_review_boundary,
            "llm_base_url": llm_base_url,
            "llm_model": llm_model,
        }

    def generate_report(self, analysis_result: dict, demo_mode: bool = False, lang: str = "en") -> str:
        """生成管理层摘要报告。

        Args:
            analysis_result: 完整的分析结果字典
            demo_mode: 是否使用演示模式（生成更丰富的报告）
            lang: 语言 ('en' or 'zh')

        Returns:
            生成的 Markdown 格式报告
        """
        metrics = self._extract_metrics(analysis_result)

        if demo_mode:
            return self._demo_report(metrics, lang)

        prompt_template = REPORT_PROMPT if lang == "zh" else REPORT_PROMPT_EN
        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | self.llm | StrOutputParser()

        try:
            report = chain.invoke(metrics)
            return report
        except Exception as e:
            return self._fallback_report(metrics, str(e), lang)

    def _demo_report(self, metrics: dict, lang: str = "en") -> str:
        """生成演示模式的管理层摘要（模拟 LLM 输出，数据驱动，无硬编码 SKU）。"""
        variance_rate = metrics['variance_rate']
        if variance_rate > 10:
            risk_level = "High Risk" if lang == "en" else "高风险"
            risk_color = "🔴"
        elif variance_rate > 5:
            risk_level = "Medium Risk" if lang == "en" else "中风险"
            risk_color = "🟡"
        else:
            risk_level = "Low Risk" if lang == "en" else "低风险"
            risk_color = "🟢"

        no_log_pct = (metrics['no_log'] / max(metrics['no_log'] + metrics['fully_explained'] + metrics['partially_explained'], 1)) * 100

        from datetime import datetime
        report_date = datetime.now().strftime("%Y-%m-%d")

        if lang == "en":
            return f"""## 📊 Executive Summary Report

> 🤖 Generated by InventoryDoc Agent on AMD Radeon GPU + ROCm
> 📅 Report Date: {report_date}
> 🏷️ run_id: {metrics['run_id']}

---

### I. Core Findings

This cycle count covers **{metrics['total_sku']}** SKUs. Key metrics:

| Metric | Value | Description |
|--------|-------|-------------|
| System Stock | {metrics['system_total']:,} pcs | ERP system record |
| Recount Total | {metrics['recount_total']:,} pcs | Actual count result |
| Net Variance | **{metrics['net_variance']:,}** pcs | {'Shortage' if metrics['net_variance'] < 0 else 'Surplus'} |
| Variance Rate | **{variance_rate}%** | {risk_color} {risk_level} |
| Net Variance Amount | **¥{metrics['net_variance_amount']:,.2f}** | Requires adjustment |

**Conclusion**: Variance rate is {variance_rate}%, at {risk_level} level.

---

### II. Risk Grading

{risk_color} **Overall Inventory Accuracy: {risk_level}**

- Variance rate {variance_rate}% {'exceeds' if variance_rate > 5 else 'below'} industry benchmark of 5%
- {metrics['loss_count'] + metrics['gain_count']} SKUs with variance ({metrics['loss_count']} shortage + {metrics['gain_count']} surplus)
- Recommendation: {'Immediate inventory rectification required' if variance_rate > 5 else 'Maintain current management level'}

{risk_color} **Category Anomaly Risk**

{metrics['category_anomalies']}

🟡 **Process Compliance: Medium Risk**

- {metrics['no_log']} SKUs ({no_log_pct:.0f}%) have no log correlation
- Recommendation: Strengthen scan compliance for traceable operations

---

### III. Top-5 Variance SKUs

{metrics['top5_sku_table']}

---

### IV. Log Correlation Analysis

| Correlation | SKUs | Amount | Ratio | Action |
|-------------|------|--------|-------|--------|
| Fully Explained | {metrics['fully_explained']} | ¥{metrics['fully_explained_amount']:,.2f} | {metrics['fully_explained_amount'] / max(abs(metrics['net_variance_amount']), 1) * 100:.1f}% | Direct adjustment |
| Partially Explained | {metrics['partially_explained']} | ¥{metrics['partially_explained_amount']:,.2f} | {metrics['partially_explained_amount'] / max(abs(metrics['net_variance_amount']), 1) * 100:.1f}% | Supplementary verification |
| No Log Correlation | {metrics['no_log']} | ¥{metrics['no_log_amount']:,.2f} | {metrics['no_log_amount'] / max(abs(metrics['net_variance_amount']), 1) * 100:.1f}% | **On-site review required** |

---

### V. Quality Gate Summary

{metrics['quality_gate_summary']}

{metrics['quality_checks']}

---

### VI. Disposition Recommendations

{metrics['disposition_recommendations_table']}

---

### VII. Deliverable Package

{metrics['deliverable_package_list']}

---

### VIII. Run Metadata

| Item | Value |
|------|-------|
| run_id | {metrics['run_id']} |
| workflow version | {metrics['workflow_version']} |
| input files | {metrics['input_file_count']} |
| workflow duration | {metrics['workflow_duration']} |
| LLM model | {metrics['llm_model']} |
| LLM service | {metrics['llm_base_url']} |

---

> 📌 Factual computation by deterministic pandas workflow; LLM only handles expression.
> 📌 All data processed locally, no external API or cloud dependency.
> 📌 This report is not a final adjustment instruction. Agent outputs recommendations; execution requires warehouse/finance/audit review.
> 📌 Data source: May cycle count data (10 files)
> 📌 Analysis method: Noise detection → Baseline selection → Variance calculation → Log correlation → Category analysis"""
        else:
            return f"""## 📊 管理层摘要报告

> 🤖 由 InventoryDoc Agent 基于 AMD Radeon GPU + ROCm 本地推理生成
> 📅 报告时间：{report_date}
> 🏷️ run_id: {metrics['run_id']}

---

### 一、核心发现

本次 5 月循环盘点覆盖 **{metrics['total_sku']}** 个 SKU。关键指标如下：

| 指标 | 数值 | 说明 |
|------|------|------|
| 系统库存 | {metrics['system_total']:,} 件 | ERP 系统记录 |
| 复盘数量 | {metrics['recount_total']:,} 件 | 实际盘点结果 |
| 净差异 | **{metrics['net_variance']:,}** 件 | {'盘亏为主' if metrics['net_variance'] < 0 else '盘盈为主'} |
| 差异率 | **{variance_rate}%** | {risk_color} {risk_level} |
| 净差异金额 | **¥{metrics['net_variance_amount']:,.2f}** | 需调账处理 |

**结论**：本次盘点差异率 {variance_rate}%，处于 {risk_level} 水平。

---

### 二、风险分级

{risk_color} **整体库存准确性：{risk_level}**

- 差异率 {variance_rate}% {'超过' if variance_rate > 5 else '低于'}行业基准 5%
- 存在差异的 SKU 共 {metrics['loss_count'] + metrics['gain_count']} 个（{metrics['loss_count']} 盘亏 + {metrics['gain_count']} 盘盈）
- 建议：{'需立即启动库存整改' if variance_rate > 5 else '维持现有管理水平'}

{risk_color} **品类异常风险**

{metrics['category_anomalies']}

🟡 **流程合规性：中风险**

- {metrics['no_log']} 个 SKU（{no_log_pct:.0f}%）无日志关联，无法追溯差异原因
- 建议：加强出入库扫码规范，确保操作可追溯

---

### 三、Top-5 差异 SKU

{metrics['top5_sku_table']}

---

### 四、日志关联分析

| 关联类别 | SKU 数 | 金额 | 占比 | 建议 |
|----------|--------|------|------|------|
| 完全可解释 | {metrics['fully_explained']} | ¥{metrics['fully_explained_amount']:,.2f} | {metrics['fully_explained_amount'] / max(abs(metrics['net_variance_amount']), 1) * 100:.1f}% | 可直接调账 |
| 部分可解释 | {metrics['partially_explained']} | ¥{metrics['partially_explained_amount']:,.2f} | {metrics['partially_explained_amount'] / max(abs(metrics['net_variance_amount']), 1) * 100:.1f}% | 需补充单据 |
| 无日志关联 | {metrics['no_log']} | ¥{metrics['no_log_amount']:,.2f} | {metrics['no_log_amount'] / max(abs(metrics['net_variance_amount']), 1) * 100:.1f}% | **需现场复核** |

---

### 五、质量门禁摘要

{metrics['quality_gate_summary']}

{metrics['quality_checks']}

---

### 六、处置建议

{metrics['disposition_recommendations_table']}

---

### 七、调账材料包

{metrics['deliverable_package_list']}

---

### 八、运行元数据

| 项目 | 值 |
|------|-----|
| run_id | {metrics['run_id']} |
| workflow 版本 | {metrics['workflow_version']} |
| 输入文件数 | {metrics['input_file_count']} |
| 工作流耗时 | {metrics['workflow_duration']} |
| LLM 模型 | {metrics['llm_model']} |
| LLM 服务 | {metrics['llm_base_url']} |

---

> 📌 事实计算由确定性 pandas 工作流完成，LLM 仅做表达。
> 📌 数据全程在本地处理，不依赖外部 API 或云服务。
> 📌 本报告不构成最终调账指令。Agent 输出建议，调账执行需由仓库 / 财务 / 审计人员复核确认。
> 📌 数据来源：某供应链 5 月循环盘点数据（10 份文件）
> 📌 分析方法：噪音识别 → 基准选择 → 差异计算 → 日志关联 → 品类分析"""

    def _fallback_report(self, metrics: dict, error: str, lang: str = "en") -> str:
        """当 LLM 不可用时，生成基于规则的摘要。"""
        if lang == "en":
            return f"""## Executive Summary (Offline Mode)

> ⚠️ **Local LLM service unavailable**, switched to rule-based summary.
> Reason: {error}
> For GPU inference, start vLLM/llama.cpp: `vllm serve <model> --host 0.0.0.0 --port 8000`
> 🏷️ run_id: {metrics['run_id']}

### Basic Overview

This cycle count covers **{metrics['total_sku']}** SKUs. System stock **{metrics['system_total']:,}** pcs, recount **{metrics['recount_total']:,}** pcs, net variance **{metrics['net_variance']:,}** pcs, variance rate **{metrics['variance_rate']}%**.

Net variance amount **{metrics['net_variance_amount']:,.2f}** CNY, shortage {metrics['loss_count']} SKUs ({metrics['total_loss_amount']:,.2f} CNY), surplus {metrics['gain_count']} SKUs ({metrics['total_gain_amount']:,.2f} CNY).

### Top-5 Variance SKUs

{metrics['top5_sku_table']}

### Quality Gate Summary

{metrics['quality_gate_summary']}

### Disposition Recommendations

{metrics['disposition_recommendations_table']}

### Deliverable Package

{metrics['deliverable_package_list']}

### Noise Processing

Scan log: {metrics['scan_total']} records, {metrics['noise_count']} ({metrics['noise_ratio']:.1f}%) NOISE interference excluded. Historical anomalies: {metrics['history_anomalies']}, related files excluded.

### Log Correlation

- Fully Explained: {metrics['fully_explained']} SKUs ({metrics['fully_explained_amount']:,.2f} CNY)
- Partially Explained: {metrics['partially_explained']} SKUs ({metrics['partially_explained_amount']:,.2f} CNY)
- No Log Correlation: {metrics['no_log']} SKUs ({metrics['no_log_amount']:,.2f} CNY) — On-site review required

### Category Anomalies

{metrics['category_anomalies']}

### Quality Checks

{metrics['quality_checks']}

### Run Metadata

| Item | Value |
|------|-------|
| run_id | {metrics['run_id']} |
| workflow version | {metrics['workflow_version']} |
| input files | {metrics['input_file_count']} |
| workflow duration | {metrics['workflow_duration']} |
| LLM model | {metrics['llm_model']} |
| LLM service | {metrics['llm_base_url']} |

---

> 📌 Factual computation by deterministic pandas workflow; LLM only handles expression.
> 📌 All data processed locally.
> 📌 Agent outputs recommendations; adjustment execution requires warehouse/finance/audit review.
> *This report was auto-generated by InventoryDoc Agent (rule-based summary mode)*"""
        else:
            return f"""## 管理层摘要（离线模式）

> ⚠️ **本地 LLM 服务不可用**，已切换为规则化摘要模式。
> 原因：{error}
> 如需 GPU 推理，请启动 vLLM/llama.cpp 服务：`vllm serve <模型名> --host 0.0.0.0 --port 8000`
> 🏷️ run_id: {metrics['run_id']}

### 基本概况

本次循环盘点覆盖 **{metrics['total_sku']}** 个 SKU，系统库存 **{metrics['system_total']:,}** 件，复盘 **{metrics['recount_total']:,}** 件，净差异 **{metrics['net_variance']:,}** 件，差异率 **{metrics['variance_rate']}%**。

净差异金额 **{metrics['net_variance_amount']:,.2f}** 元，其中盘亏 {metrics['loss_count']} 个 SKU（{metrics['total_loss_amount']:,.2f} 元），盘盈 {metrics['gain_count']} 个 SKU（{metrics['total_gain_amount']:,.2f} 元）。

### Top-5 差异 SKU

{metrics['top5_sku_table']}

### 质量门禁摘要

{metrics['quality_gate_summary']}

### 处置建议

{metrics['disposition_recommendations_table']}

### 调账材料包

{metrics['deliverable_package_list']}

### 噪音数据处理

扫描日志共 {metrics['scan_total']} 条记录，其中 {metrics['noise_count']} 条（{metrics['noise_ratio']:.1f}%）为 NOISE 干扰数据，已自动排除。历史异常数据 {metrics['history_anomalies']} 条，相关文件已排除。

### 日志关联分析

- 完全可解释：{metrics['fully_explained']} 个 SKU（{metrics['fully_explained_amount']:,.2f} 元）
- 部分可解释：{metrics['partially_explained']} 个 SKU（{metrics['partially_explained_amount']:,.2f} 元）
- 无日志关联：{metrics['no_log']} 个 SKU（{metrics['no_log_amount']:,.2f} 元）— 需现场复核

### 品类异常

{metrics['category_anomalies']}

### 质量校验

{metrics['quality_checks']}

### 运行元数据

| 项目 | 值 |
|------|-----|
| run_id | {metrics['run_id']} |
| workflow 版本 | {metrics['workflow_version']} |
| 输入文件数 | {metrics['input_file_count']} |
| 工作流耗时 | {metrics['workflow_duration']} |
| LLM 模型 | {metrics['llm_model']} |
| LLM 服务 | {metrics['llm_base_url']} |

---

> 📌 事实计算由确定性 pandas 工作流完成，LLM 仅做表达。
> 📌 数据全程在本地处理。
> 📌 Agent 输出建议，调账执行需由仓库 / 财务 / 审计人员复核确认。
> *此报告由 InventoryDoc Agent 自动生成（规则化摘要模式，非 LLM 输出）*"""


def generate_from_file(result_path: str, output_path: Optional[str] = None) -> str:
    """从 analysis_result.json 文件生成报告。

    Args:
        result_path: analysis_result.json 的路径
        output_path: 可选的报告输出路径

    Returns:
        生成的报告内容
    """
    from .agent import load_config

    # 读取分析结果
    with open(result_path, "r", encoding="utf-8") as f:
        analysis_result = json.load(f)

    # 生成报告
    config = load_config()
    generator = ReportGenerator(config)
    report = generator.generate_report(analysis_result)

    # 保存报告
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

    return report


if __name__ == "__main__":
    # 测试：从文件生成报告
    import sys
    if len(sys.argv) > 1:
        result_file = sys.argv[1]
    else:
        result_file = "data/output/analysis_result.json"

    output_file = "data/output/管理层摘要报告.md"
    report = generate_from_file(result_file, output_file)
    print(f"报告已生成: {output_file}")
    print("\n" + report)
