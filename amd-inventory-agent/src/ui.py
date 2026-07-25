"""
UI — Gradio Web 界面。
提供数据上传、工作流执行、对话式交互、结果查看功能。
支持对话历史持久化，刷新页面不丢失。
"""

import gradio as gr
from pathlib import Path
import pandas as pd
import json
from datetime import datetime


class ChatEngine:
    """基于分析结果的对话引擎，支持多轮交互 + 历史持久化。"""

    def __init__(self, history_file: str = "data/chat_history.json"):
        self.analysis_result = None
        self.variance_df = None
        self.initialized = False
        self.history_file = Path(history_file)
        self.chat_history = self._load_history()

    def _load_history(self) -> list:
        """从文件加载对话历史。"""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_history(self):
        """保存对话历史到文件。"""
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self.chat_history, f, ensure_ascii=False, indent=2)

    def get_history(self) -> list:
        """获取格式化的对话历史（Gradio Chatbot 格式）。"""
        return [{"role": h["role"], "content": h["content"]} for h in self.chat_history]

    def add_to_history(self, role: str, content: str):
        """添加一条消息到历史。"""
        self.chat_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        self._save_history()

    def clear_history(self):
        """清空对话历史。"""
        self.chat_history = []
        self._save_history()

    def export_to_markdown(self) -> str:
        """导出对话历史为 Markdown 格式。"""
        if not self.chat_history:
            return "# 对话记录\n\n暂无对话记录。"

        lines = [
            "# InventoryDoc Agent 对话记录",
            f"\n> 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
            "---\n",
        ]

        for entry in self.chat_history:
            role = "用户" if entry["role"] == "user" else "Agent"
            timestamp = entry.get("timestamp", "")
            time_str = ""
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    time_str = f" *({dt.strftime('%H:%M')})*"
                except Exception:
                    pass

            lines.append(f"### {role}{time_str}\n")
            lines.append(f"{entry['content']}\n")
            lines.append("---\n")

        return "\n".join(lines)

    def save_markdown(self) -> str:
        """保存对话记录为 Markdown 文件，返回文件路径。"""
        md_content = self.export_to_markdown()
        export_dir = Path("data/output")
        export_dir.mkdir(parents=True, exist_ok=True)
        filename = f"对话记录_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        filepath = export_dir / filename
        filepath.write_text(md_content, encoding="utf-8")
        return str(filepath)

    def load_analysis(self, result: dict, variance_df=None):
        """加载分析结果。"""
        self.analysis_result = result
        self.variance_df = variance_df
        self.initialized = True

    def answer(self, question: str) -> str:
        """根据问题返回答案。"""
        if not self.initialized:
            return "请先运行分析，然后再提问。"

        q = question.lower()

        # 总体概况
        if any(kw in q for kw in ["总体", "概况", "总结", "汇总", "一共", "总共", "summary"]):
            return self._answer_overview()

        # 差异率
        if any(kw in q for kw in ["差异率", "差异比例", "rate"]):
            return self._answer_variance_rate()

        # 盘亏
        if any(kw in q for kw in ["盘亏", "少了", "丢失", "亏", "loss"]):
            return self._answer_loss()

        # 盘盈
        if any(kw in q for kw in ["盘盈", "多了", "盈", "gain"]):
            return self._answer_gain()

        # 异常品类
        if any(kw in q for kw in ["异常", "品类", "哪个品类", "最严重", "anomaly", "category"]):
            return self._answer_anomaly_category()

        # 日志关联
        if any(kw in q for kw in ["日志", "关联", "解释", "scan", "log", "可解释"]):
            return self._answer_log_correlation()

        # 库位
        if any(kw in q for kw in ["库位", "停用", "维修", "location", "正常"]):
            return self._answer_location()

        # 噪音
        if any(kw in q for kw in ["噪音", "noise", "排除", "干扰"]):
            return self._answer_noise()

        # 质量校验
        if any(kw in q for kw in ["质量", "校验", "check", "quality", "通过"]):
            return self._answer_quality()

        # 金额
        if any(kw in q for kw in ["金额", "多少钱", "元", "成本", "amount", "money"]):
            return self._answer_amount()

        # 建议
        if any(kw in q for kw in ["建议", "怎么处理", "下一步", "recommend", "advice"]):
            return self._answer_recommendation()

        # 重点 SKU
        if any(kw in q for kw in ["重点", "top", "最多", "最大", "关键"]):
            return self._answer_top_sku()

        # 具体 SKU 查询
        if any(kw in q for kw in ["sku", "型号", "查", "查一下"]):
            return self._answer_sku_query(question)

        # 帮助
        if any(kw in q for kw in ["帮助", "help", "能做什么", "怎么用"]):
            return self._answer_help()

        return self._answer_default(question)

    def _get_step(self, step_name):
        return self.analysis_result.get(step_name, {})

    def _answer_overview(self) -> str:
        step5 = self._get_step("Step 5: 加载盘点结果")
        step6 = self._get_step("Step 6: 计算差异金额")
        step7 = self._get_step("Step 7: 日志关联分析")

        lines = [
            "## 盘点概况",
            f"- SKU 总数：**{step5.get('total_sku', 0)}** 个",
            f"- 系统库存：**{step5.get('system_total', 0):,}** 件",
            f"- 复盘数量：**{step5.get('recount_total', 0):,}** 件",
            f"- 净差异：**{step5.get('net_variance', 0):,}** 件",
            f"- 总体差异率：**{step5.get('variance_rate', 0)}%**",
            f"- 盘亏 SKU：**{step5.get('loss_count', 0)}** 个",
            f"- 盘盈 SKU：**{step5.get('gain_count', 0)}** 个",
            f"- 初盘纠错：**{step5.get('correction_count', 0)}** 个",
            "",
            f"净差异金额：**{step6.get('net_variance_amount', 0):,.2f}** 元",
        ]

        if isinstance(step7, dict) and "无日志关联" in step7:
            no_log = step7["无日志关联"]
            lines.append(f"无日志关联 SKU：**{no_log.get('count', 0)}** 个（金额 {no_log.get('amount', 0):,.2f} 元）— 这些需要现场实物复核")

        return "\n".join(lines)

    def _answer_variance_rate(self) -> str:
        step5 = self._get_step("Step 5: 加载盘点结果")
        rate = step5.get("variance_rate", 0)
        level = "正常（<3%）" if rate < 3 else ("关注（3-8%）" if rate < 8 else "严重（>8%）")
        return f"总体差异率：**{rate}%**，判断为**{level}**。\n\n注意：总体差异率可能掩盖局部严重问题，请查看品类维度分析。"

    def _answer_loss(self) -> str:
        step5 = self._get_step("Step 5: 加载盘点结果")
        step6 = self._get_step("Step 6: 计算差异金额")
        return (
            f"## 盘亏情况\n\n"
            f"- 盘亏 SKU：**{step5.get('loss_count', 0)}** 个\n"
            f"- 盘亏金额：**{step6.get('total_loss_amount', 0):,.2f}** 元\n\n"
            f"盘亏 = 实盘数量少于系统记录，可能原因：丢失、未扫码出库、数据录入错误。"
        )

    def _answer_gain(self) -> str:
        step5 = self._get_step("Step 5: 加载盘点结果")
        step6 = self._get_step("Step 6: 计算差异金额")
        return (
            f"## 盘盈情况\n\n"
            f"- 盘盈 SKU：**{step5.get('gain_count', 0)}** 个\n"
            f"- 盘盈金额：**{step6.get('total_gain_amount', 0):,.2f}** 元\n\n"
            f"盘盈 = 实盘数量多于系统记录，可能原因：入库未扫码、退货未入账、数据录入错误。"
        )

    def _answer_anomaly_category(self) -> str:
        step9 = self._get_step("Step 9: 品类维度分析")
        categories = step9.get("categories", [])
        anomalies = step9.get("anomaly_categories", [])

        lines = ["## 品类差异分析（按差异率降序）\n"]
        lines.append("| 品类 | SKU 数 | 系统库存 | 差异率 |")
        lines.append("|---|---|---|---|")

        for cat in categories:
            name = cat.get("品类", "")
            rate = cat.get("差异率", 0)
            marker = " ⚠️" if rate > 5 else ""
            lines.append(f"| {name}{marker} | {cat.get('SKU数量', 0)} | {cat.get('系统库存总计', 0):,} | {rate}% |")

        if anomalies:
            lines.append("\n### 异常品类")
            for a in anomalies:
                lines.append(f"- **{a['品类']}**：差异率 {a['差异率']}%（{a['严重程度']}）")

        return "\n".join(lines)

    def _answer_log_correlation(self) -> str:
        step7 = self._get_step("Step 7: 日志关联分析")
        if not isinstance(step7, dict) or "error" in step7:
            return "日志关联数据不可用。"

        lines = ["## 扫描日志关联分析\n"]
        lines.append("| 关联类别 | SKU 数 | 差异金额 (元) | 说明 |")
        lines.append("|---|---|---|---|")
        lines.append(f"| 完全可解释 | {step7.get('完全可解释', {}).get('count', 0)} | {step7.get('完全可解释', {}).get('amount', 0):,.2f} | 有对应出入库操作，可直接调账 |")
        lines.append(f"| 部分可解释 | {step7.get('部分可解释', {}).get('count', 0)} | {step7.get('部分可解释', {}).get('amount', 0):,.2f} | 有操作但量不足，需补充核实 |")
        lines.append(f"| 无日志关联 | {step7.get('无日志关联', {}).get('count', 0)} | {step7.get('无日志关联', {}).get('amount', 0):,.2f} | **需现场实物复核** |")

        return "\n".join(lines)

    def _answer_location(self) -> str:
        step8 = self._get_step("Step 8: 库位状态校验")
        dist = step8.get("status_distribution", {})
        abnormal = step8.get("abnormal_count", 0)

        lines = [
            "## 库位状态分析\n",
            f"- 启用库位差异 SKU：**{dist.get('启用', 0)}** 个",
            f"- 已停用库位差异 SKU：**{dist.get('已停用', 0)}** 个",
            f"- 维修中库位差异 SKU：**{dist.get('维修中', 0)}** 个",
            f"- 异常库位 SKU 总计：**{abnormal}** 个",
            "",
            "⚠️ 落在已停用/维修中库位的差异，应作为库位管理遗留问题区别对待，不能简单追责。",
        ]
        return "\n".join(lines)

    def _answer_noise(self) -> str:
        step2 = self._get_step("Step 2: 识别噪音数据")
        noise_log = step2.get("scan_log_noise", {})
        noise_files = step2.get("noise_files", [])

        lines = [
            "## 噪音识别结果\n",
            f"### 扫描日志",
            f"- NOISE 干扰记录：**{noise_log.get('noise_count', 0)}** 条（型号以 NOISE- 开头）",
            f"- 真实操作记录：**{noise_log.get('real_count', 0)}** 条",
            "",
            f"### 噪音文件",
            f"- 排除 **{len(noise_files)}** 个不适用文件",
        ]
        for f in noise_files:
            lines.append(f"  - ❌ {f}")

        return "\n".join(lines)

    def _answer_quality(self) -> str:
        checks = self.analysis_result.get("quality_checks", [])
        passed = sum(1 for c in checks if c.get("passed", False))

        lines = [f"## 质量校验：{passed}/{len(checks)} 通过\n"]
        for i, check in enumerate(checks, 1):
            status = "✅" if check.get("passed") else "❌"
            lines.append(f"{status} **{i}. {check.get('name', '')}** ({check.get('importance', '')})")
            lines.append(f"   {check.get('detail', '')}\n")

        return "\n".join(lines)

    def _answer_amount(self) -> str:
        step6 = self._get_step("Step 6: 计算差异金额")
        return (
            "## 差异金额\n\n"
            f"- 盘亏金额：**{step6.get('total_loss_amount', 0):,.2f}** 元\n"
            f"- 盘盈金额：**{step6.get('total_gain_amount', 0):,.2f}** 元\n"
            f"- 净差异金额：**{step6.get('net_variance_amount', 0):,.2f}** 元\n"
            f"- 缺失成本 SKU：**{step6.get('missing_cost_count', 0)}** 个（已用同品类均值估算）\n\n"
            "金额按**成本单价**计算（非售价），确保财务影响估算准确。"
        )

    def _answer_recommendation(self) -> str:
        step5 = self._get_step("Step 5: 加载盘点结果")
        step7 = self._get_step("Step 7: 日志关联分析")
        step9 = self._get_step("Step 9: 品类维度分析")

        lines = ["## 处理建议\n"]

        # 紧急
        anomalies = step9.get("anomaly_categories", [])
        severe = [a for a in anomalies if a.get("严重程度") == "严重异常"]
        if severe:
            lines.append("### 🔴 紧急（本周内）")
            for a in severe:
                lines.append(f"- **{a['品类']}**（差异率 {a['差异率']}%）：全品类复盘，重点 SKU 实物复核")
            lines.append("")

        # 重要
        no_log = step7.get("无日志关联", {}).get("count", 0) if isinstance(step7, dict) else 0
        if no_log > 0:
            lines.append("### 🟡 重要（两周内）")
            lines.append(f"- **{no_log}** 个无日志关联 SKU 逐一排查")
            lines.append("- 差异金额 >2000 元的 SKU 追责")
            lines.append("- 已停用库位集中差异的库位清理")
            lines.append("")

        # 流程优化
        lines.append("### 🟢 流程优化")
        lines.append("- 扫描日志完整性提升（减少 NOISE 干扰）")
        lines.append("- 初盘双人复核机制")
        lines.append("- 停用库位定期清理")
        lines.append("- 出入库记录与系统日志的定期对账")

        return "\n".join(lines)

    def _answer_top_sku(self) -> str:
        if self.variance_df is None:
            return "差异数据不可用，请先运行分析。"

        df = self.variance_df.copy()
        diff_df = df[df["差异数量"] != 0].copy()
        diff_df["差异金额绝对值"] = diff_df["差异金额"].abs()
        top = diff_df.nlargest(10, "差异金额绝对值")

        lines = ["## Top 10 差异 SKU（按差异金额绝对值降序）\n"]
        lines.append("| 型号 | 品类 | 系统库存 | 复盘数 | 差异 | 差异金额 | 类型 |")
        lines.append("|---|---|---|---|---|---|---|")

        for _, row in top.iterrows():
            lines.append(
                f"| {row.get('型号', '')} | {row.get('品类', '')} | "
                f"{row.get('系统库存数', 0)} | {row.get('复盘数', 0)} | "
                f"{row.get('差异数量', 0)} | {row.get('差异金额', 0):,.2f} | "
                f"{row.get('差异类型', '')} |"
            )

        return "\n".join(lines)

    def _answer_sku_query(self, question: str) -> str:
        if self.variance_df is None:
            return "差异数据不可用，请先运行分析。"

        # 提取型号关键词
        df = self.variance_df.copy()
        for word in question.replace("查一下", "").replace("查", "").replace("sku", "").replace("型号", "").split():
            if len(word) >= 3:
                matches = df[df["型号"].astype(str).str.contains(word, na=False)]
                if len(matches) > 0:
                    lines = [f"## 查询结果：匹配到 {len(matches)} 个 SKU\n"]
                    for _, row in matches.head(10).iterrows():
                        lines.append(
                            f"- **{row.get('型号', '')}**（{row.get('品类', '')}）："
                            f"系统库存 {row.get('系统库存数', 0)}，复盘 {row.get('复盘数', 0)}，"
                            f"差异 {row.get('差异数量', 0)}，金额 {row.get('差异金额', 0):,.2f} 元"
                        )
                    return "\n".join(lines)

        return f"未找到匹配的 SKU。请尝试输入具体的型号，如 K-1381T-S-0。"

    def _answer_help(self) -> str:
        return (
            "## 我能回答的问题\n\n"
            "- **总体概况**：系统库存、差异率、盘亏盘盈统计\n"
            "- **差异率**：总体差异率和严重程度判断\n"
            "- **盘亏/盘盈**：具体数量和金额\n"
            "- **异常品类**：哪个品类差异最严重\n"
            "- **日志关联**：哪些差异能被操作记录解释\n"
            "- **库位状态**：停用/维修中库位的差异情况\n"
            "- **噪音识别**：排除了多少干扰数据\n"
            "- **质量校验**：7 条规则的通过情况\n"
            "- **金额**：盘亏/盘盈/净差异金额\n"
            "- **建议**：处理建议（紧急/重要/流程优化）\n"
            "- **重点 SKU**：差异最大的 10 个 SKU\n"
            "- **查 SKU**：输入型号查询具体 SKU 信息\n\n"
            "试试问我：「总体差异率是多少」「哪个品类最异常」「日志关联分析结果」「给我建议」"
        )

    def _answer_default(self, question: str) -> str:
        return (
            f"抱歉，我暂时无法理解「{question}」。\n\n"
            "试试这些问题：\n"
            "- 总体概况\n"
            "- 差异率是多少\n"
            "- 哪个品类异常\n"
            "- 日志关联分析\n"
            "- 给我处理建议\n"
            "- 查一下 K-1381T"
        )


def create_ui(agent):
    """创建 Gradio Web UI。"""
    chat_engine = ChatEngine(history_file="data/chat_history.json")

    def run_analysis(input_dir):
        if not input_dir or not Path(input_dir).exists():
            return "请输入有效的输入目录路径", "", ""

        output_dir = str(Path(input_dir).parent / "output")
        result = agent.run_workflow(input_dir, output_dir)

        # 加载到对话引擎
        chat_engine.load_analysis(result, agent._variance_df)

        # 生成摘要
        step5 = result.get("Step 5: 加载盘点结果", {})
        step6 = result.get("Step 6: 计算差异金额", {})
        step7 = result.get("Step 7: 日志关联分析", {})

        summary = f"## 分析完成\n\n"
        summary += f"- SKU 总数：**{step5.get('total_sku', 0)}** 个\n"
        summary += f"- 系统库存：**{step5.get('system_total', 0):,}** 件\n"
        summary += f"- 净差异：**{step5.get('net_variance', 0):,}** 件\n"
        summary += f"- 差异率：**{step5.get('variance_rate', 0)}%**\n"
        summary += f"- 盘亏：**{step5.get('loss_count', 0)}** 个 | 盘盈：**{step5.get('gain_count', 0)}** 个\n"
        summary += f"- 净差异金额：**{step6.get('net_variance_amount', 0):,.2f}** 元\n"

        if isinstance(step7, dict) and "无日志关联" in step7:
            no_log = step7["无日志关联"]
            summary += f"- 无日志关联 SKU：**{no_log.get('count', 0)}** 个（需现场复核）\n"

        # 质量校验
        checks = result.get("quality_checks", [])
        passed = sum(1 for c in checks if c.get("passed", False))
        summary += f"\n质量校验：**{passed}/{len(checks)}** 通过\n"

        quality_report = f"## 质量校验报告\n\n"
        for i, check in enumerate(checks, 1):
            status = "✅" if check.get("passed", False) else "❌"
            quality_report += f"{status} **{i}. {check.get('name', '')}** ({check.get('importance', '')})\n"
            quality_report += f"   {check.get('detail', '')}\n\n"

        deliverables = result.get("Step 10: 生成交付物", {})
        deliverable_info = f"## 交付物\n\n"
        deliverable_info += f"- Excel: `{deliverables.get('xlsx_path', '未生成')}`\n"
        deliverable_info += f"- 报告: `{deliverables.get('md_path', '未生成')}`\n"
        deliverable_info += f"\n💡 **现在可以到「对话」标签页追问分析结果！**"

        return summary, quality_report, deliverable_info

    def chat_response(message, history):
        """对话式交互，带加载动画 + 历史持久化。"""
        import time

        # 显示"正在思考..."
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": "⏳ 正在思考..."})
        yield history, ""

        # 模拟短暂延迟（让动画可见）
        time.sleep(0.3)

        # 获取实际回答
        response = chat_engine.answer(message)

        # 保存到持久化历史
        chat_engine.add_to_history("user", message)
        chat_engine.add_to_history("assistant", response)

        # 替换为实际回答
        history[-1] = {"role": "assistant", "content": response}
        yield history, ""

    def clear_chat():
        """清空对话历史。"""
        chat_engine.clear_history()
        return [], ""

    def export_chat():
        """导出对话为 Markdown 文件。"""
        filepath = chat_engine.save_markdown()
        return f"✅ 已导出到：`{filepath}`"

    with gr.Blocks(title="InventoryDoc Agent") as ui:
        gr.Markdown(
            "# InventoryDoc Agent\n"
            "*基于 AMD Radeon GPU + ROCm 的库存盘点差异智能分析助手*"
        )

        with gr.Tabs():
            with gr.TabItem("分析"):
                input_dir = gr.Textbox(
                    label="输入数据目录",
                    placeholder="例如: data/input",
                    value="data/input",
                )
                run_btn = gr.Button("开始分析", variant="primary")

                summary_output = gr.Markdown(label="分析摘要")
                quality_output = gr.Markdown(label="质量校验")
                deliverable_output = gr.Markdown(label="交付物")

                run_btn.click(
                    run_analysis,
                    [input_dir],
                    [summary_output, quality_output, deliverable_output],
                )

            with gr.TabItem("📊 管理层报告"):
                gr.Markdown(
                    "### 📊 AI 生成管理层摘要\n"
                    "基于分析结果，使用本地 LLM 生成面向管理层的摘要报告。\n"
                    "包含：管理层摘要、风险分级、Top-5 异常 SKU 解读、行动建议。\n\n"
                    "> ⚠️ 需要先启动 vLLM/llama.cpp 服务（端口 8000）"
                )
                generate_report_btn = gr.Button("生成管理层报告", variant="primary")
                report_output = gr.Markdown(label="管理层报告")

                def generate_report():
                    if not chat_engine.initialized:
                        return "请先在「分析」标签页运行分析，然后再生成报告。"
                    return agent.generate_executive_report()

                generate_report_btn.click(generate_report, outputs=[report_output])

            with gr.TabItem("对话"):
                gr.Markdown(
                    "### 💬 追问分析结果\n"
                    "分析完成后，在这里追问具体问题。对话历史自动保存，刷新页面不丢失。\n"
                    "试试：\n"
                    "- 「总体概况」\n"
                    "- 「哪个品类最异常」\n"
                    "- 「日志关联分析」\n"
                    "- 「给我处理建议」\n"
                    "- 「查一下 K-1381T」"
                )
                chatbot = gr.Chatbot(
                    height=400,
                    label="对话",
                    value=chat_engine.get_history(),
                    render_markdown=True,
                )
                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder="输入你的问题...",
                        label="",
                        scale=8,
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)
                    export_btn = gr.Button("📥 导出 Markdown", variant="secondary", scale=1)
                    clear_btn = gr.Button("🗑️ 清空历史", variant="stop", scale=1)

                export_status = gr.Markdown()

                send_btn.click(chat_response, [msg_input, chatbot], [chatbot, msg_input])
                msg_input.submit(chat_response, [msg_input, chatbot], [chatbot, msg_input])
                export_btn.click(export_chat, outputs=[export_status])
                clear_btn.click(clear_chat, outputs=[chatbot, msg_input])

            with gr.TabItem("关于"):
                gr.Markdown(
                    "## 功能说明\n\n"
                    "本 Agent 自动完成库存盘点差异分析的 10 步工作流：\n\n"
                    "1. 加载多格式数据文件（CSV/XLSX/TXT）\n"
                    "2. 识别并排除噪音数据\n"
                    "3. 选定系统库存比对基准\n"
                    "4. 清洗扫描日志（NOISE 过滤）\n"
                    "5. 加载盘点结果（以复盘数为准）\n"
                    "6. 计算差异金额（成本单价口径）\n"
                    "7. 日志关联分析（三分类）\n"
                    "8. 库位状态校验\n"
                    "9. 品类维度分析\n"
                    "10. 生成交付物（XLSX + MD）\n\n"
                    "内置 7 条质量校验规则，确保输出符合企业级标准。\n\n"
                    "### GPU 推理能力\n\n"
                    "基于 AMD Radeon GPU + ROCm，通过 vLLM/llama.cpp 本地运行 LLM：\n"
                    "- 生成管理层摘要报告\n"
                    "- 风险分级（高/中/低）\n"
                    "- Top-5 异常 SKU 解读\n"
                    "- 下一步行动建议\n\n"
                    "### 使用流程\n\n"
                    "1. 在「分析」标签页输入数据目录，点击「开始分析」\n"
                    "2. 分析完成后，切换到「📊 管理层报告」标签页生成 AI 摘要\n"
                    "3. 切换到「对话」标签页追问具体问题\n"
                    "4. 支持的问题类型：概况、差异率、品类、日志关联、库位、噪音、质量、金额、建议、SKU 查询"
                )

        return ui
