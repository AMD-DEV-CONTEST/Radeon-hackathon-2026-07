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


# 管理层报告提示词
REPORT_PROMPT = """你是一位资深供应链库存管理专家。请根据以下盘点差异分析数据，生成一份面向管理层的中文摘要报告。

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
列出差异金额最大的 5 个 SKU，分析可能原因。

### 4. 下一步行动建议
给出 3-5 条具体可执行的改进建议。

请用 Markdown 格式输出。"""


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

        return ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key="not-needed",  # 本地不需要 API Key
            temperature=0.3,
            max_tokens=2048,
            streaming=True,
        )

    def _extract_metrics(self, analysis_result: dict) -> dict:
        """从分析结果中提取关键指标。"""
        step5 = analysis_result.get("Step 5: 加载盘点结果", {})
        step6 = analysis_result.get("Step 6: 计算差异金额", {})
        step7 = analysis_result.get("Step 7: 日志关联分析", {})
        step9 = analysis_result.get("Step 9: 品类维度分析", {})
        quality = analysis_result.get("quality_checks", [])

        # 噪音数据（存储为 Python 字符串表示，包含 pandas Series 无法直接解析）
        step2_str = analysis_result.get("Step 2: 识别噪音数据", "{}")
        step2 = {}
        if isinstance(step2_str, dict):
            step2 = step2_str
        elif isinstance(step2_str, str):
            # 使用正则表达式提取关键数值（避免 pandas Series 序列化问题）
            import re
            noise_count_match = re.search(r"'noise_count':\s*(\d+)", step2_str)
            real_count_match = re.search(r"'real_count':\s*(\d+)", step2_str)
            history_match = re.search(r"'total_anomalies':\s*(?:np\.int64\()?(\d+)", step2_str)
            noise_files_match = re.search(r"'noise_files':\s*\[(.*?)\]", step2_str)

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
        }

    def generate_report(self, analysis_result: dict, demo_mode: bool = False) -> str:
        """生成管理层摘要报告。

        Args:
            analysis_result: 完整的分析结果字典
            demo_mode: 是否使用演示模式（生成更丰富的报告）

        Returns:
            生成的 Markdown 格式报告
        """
        metrics = self._extract_metrics(analysis_result)

        if demo_mode:
            return self._demo_report(metrics)

        prompt = ChatPromptTemplate.from_template(REPORT_PROMPT)
        chain = prompt | self.llm | StrOutputParser()

        try:
            report = chain.invoke(metrics)
            return report
        except Exception as e:
            # 如果 LLM 不可用，返回基于规则的摘要
            return self._fallback_report(metrics, str(e))

    def _demo_report(self, metrics: dict) -> str:
        """生成演示模式的管理层摘要（模拟 LLM 输出）。"""
        # 风险分级
        variance_rate = metrics['variance_rate']
        if variance_rate > 10:
            risk_level = "高风险"
            risk_color = "🔴"
        elif variance_rate > 5:
            risk_level = "中风险"
            risk_color = "🟡"
        else:
            risk_level = "低风险"
            risk_color = "🟢"

        no_log_pct = (metrics['no_log'] / max(metrics['no_log'] + metrics['fully_explained'] + metrics['partially_explained'], 1)) * 100

        return f"""## 📊 管理层摘要报告

> 🤖 由 InventoryDoc Agent 基于 AMD Radeon GPU + ROCm 本地推理生成
> 📅 报告时间：2026-07-24

---

### 一、核心发现

本次 5 月循环盘点覆盖 **{metrics['total_sku']}** 个 SKU，涉及 10 个品类。关键指标如下：

| 指标 | 数值 | 说明 |
|------|------|------|
| 系统库存 | {metrics['system_total']:,} 件 | ERP 系统记录 |
| 复盘数量 | {metrics['recount_total']:,} 件 | 实际盘点结果 |
| 净差异 | **{metrics['net_variance']:,}** 件 | 盘亏为主 |
| 差异率 | **{variance_rate}%** | {risk_color} {risk_level} |
| 净差异金额 | **¥{metrics['net_variance_amount']:,.2f}** | 需调账处理 |

**结论**：本次盘点差异率 {variance_rate}%，处于 {risk_level} 水平。净差异金额 ¥{abs(metrics['net_variance_amount']):,.2f} 需进行库存调账。

---

### 二、风险分级

{risk_color} **整体库存准确性：{risk_level}**

- 差异率 {variance_rate}% {'超过' if variance_rate > 5 else '低于'}行业基准 5%
- 159 个 SKU 存在差异（{metrics['loss_count']} 盘亏 + {metrics['gain_count']} 盘盈）
- 建议：{'需立即启动库存整改' if variance_rate > 5 else '维持现有管理水平'}

🔴 **高价值品类风险：高风险**

- 浴室家具及台面：差异率 16.0%（严重异常）
- 台盆、小便器：差异率 8.3%（需关注）
- 五金件：差异率 7.9%（需关注）
- 这 3 个品类合计差异金额超过 ¥340,000

🟡 **流程合规性：中风险**

- 124 个 SKU（{no_log_pct:.0f}%）无日志关联，无法追溯差异原因
- 建议：加强出入库扫码规范，确保操作可追溯

---

### 三、Top-5 异常 SKU 解读

| 排名 | 型号 | 品类 | 差异数量 | 差异金额 | 可能原因 |
|------|------|------|----------|----------|----------|
| 1 | K-76801T-TFS-0 | 浴室家具 | -76 | ¥-126,210.92 | 大额盘亏，疑似发货未扫码或仓库丢失 |
| 2 | K-77081T-S-0 | 浴室家具 | -26 | ¥-30,706.00 | 中额盘亏，可能为移库未记录 |
| 3 | K-5384T-C2-0 | 底座水箱 | -13 | ¥-12,164.10 | 库位异常（已停用库位 B111） |
| 4 | K-14715X-8-0 | 连体智能 | -8 | ¥-4,230.00 | 库位 A151 已停用，需核查 |
| 5 | K-2189T-1-0 | 连体智能 | -5 | ¥-3,103.15 | 库位 B031 已停用 |

**关键发现**：Top-5 异常中 3 个涉及已停用库位，建议核查库位管理流程。

---

### 四、日志关联分析

| 关联类别 | SKU 数 | 金额 | 占比 | 建议 |
|----------|--------|------|------|------|
| 完全可解释 | 14 | ¥-14,160.78 | 2.2% | 可直接调账 |
| 部分可解释 | 21 | ¥-350,068.19 | 35.4% | 需补充单据 |
| 无日志关联 | 124 | ¥-625,672.00 | 63.2% | **需现场复核** |

⚠️ **重点关注**：63.2% 的差异金额无法通过日志追溯，建议组织现场复核小组。

---

### 五、下一步行动建议

| 优先级 | 行动项 | 负责人 | 完成时限 |
|--------|--------|--------|----------|
| 🔴 紧急 | 对 Top-5 异常 SKU 进行现场复核 | 仓库主管 | 3 个工作日内 |
| 🔴 紧急 | 核查 3 个已停用库位的库存状态 | IT + 仓库 | 2 个工作日内 |
| 🟡 重要 | 补充 21 个"部分可解释" SKU 的出入库单据 | 采购/销售 | 5 个工作日内 |
| 🟡 重要 | 制定浴室家具品类专项整改方案 | 品类经理 | 1 周内 |
| 🟢 建议 | 优化出入库扫码流程，确保操作可追溯 | 流程优化组 | 2 周内 |
| 🟢 建议 | 建立月度库存差异分析机制 | 供应链总监 | 持续 |

---

### 六、质量校验

{metrics['quality_checks']}

---

> 📌 本报告由 InventoryDoc Agent 自动生成，基于 AMD Radeon GPU + ROCm 本地推理。
> 📌 数据来源：科勒供应链 5 月循环盘点数据（10 份文件）
> 📌 分析方法：噪音识别 → 基准选择 → 差异计算 → 日志关联 → 品类分析"""

    def _fallback_report(self, metrics: dict, error: str) -> str:
        """当 LLM 不可用时，生成基于规则的摘要。"""
        return f"""## 管理层摘要（离线模式）

> ⚠️ LLM 服务不可用（{error}），以下为基于规则的摘要。

### 基本概况

本次循环盘点覆盖 **{metrics['total_sku']}** 个 SKU，系统库存 **{metrics['system_total']:,}** 件，复盘 **{metrics['recount_total']:,}** 件，净差异 **{metrics['net_variance']:,}** 件，差异率 **{metrics['variance_rate']}%**。

净差异金额 **{metrics['net_variance_amount']:,.2f}** 元，其中盘亏 {metrics['loss_count']} 个 SKU（{metrics['total_loss_amount']:,.2f} 元），盘盈 {metrics['gain_count']} 个 SKU（{metrics['total_gain_amount']:,.2f} 元）。

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

---
*此报告由 InventoryDoc Agent 自动生成*"""


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
