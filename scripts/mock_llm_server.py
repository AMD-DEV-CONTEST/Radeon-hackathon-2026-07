#!/usr/bin/env python3
"""
Mock LLM Server - 模拟 OpenAI 兼容 API 用于测试。
无需实际模型，返回基于模板的响应。

用法:
    python3 scripts/mock_llm_server.py [--port 8000]

启动后，report_generator.py 可以连接到此服务器生成报告。
"""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# 分析数据模板
ANALYSIS_TEMPLATE = """你是一位资深供应链库存管理专家。请根据以下盘点差异分析数据，生成一份面向管理层的中文摘要报告。

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


class MockLLMHandler(BaseHTTPRequestHandler):
    """Mock LLM API Handler"""

    def do_GET(self):
        """处理 GET 请求（模型列表）"""
        if self.path == "/v1/models":
            response = {
                "object": "list",
                "data": [
                    {
                        "id": "mock-qwen-1.5b",
                        "object": "model",
                        "created": 1234567890,
                        "owned_by": "mock"
                    }
                ]
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        """处理 POST 请求（聊天完成）"""
        if self.path == "/v1/chat/completions":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            request = json.loads(post_data)

            # 提取用户消息
            messages = request.get("messages", [])
            user_message = ""
            for msg in messages:
                if msg.get("role") == "user":
                    user_message = msg.get("content", "")

            # 生成响应
            response_content = self._generate_response(user_message)

            response = {
                "id": "mock-response-123",
                "object": "chat.completion",
                "created": 1234567890,
                "model": request.get("model", "mock-qwen-1.5b"),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response_content
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 500,
                    "total_tokens": 600
                }
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_error(404)

    def _generate_response(self, prompt: str) -> str:
        """基于提示生成响应"""
        # 从提示中提取关键数据
        import re

        # 提取数值
        total_sku = self._extract_number(prompt, r"SKU 总数：(\d+)")
        system_total = self._extract_number(prompt, r"系统库存：([\d,]+)")
        net_variance = self._extract_number(prompt, r"净差异：([-\d,]+)")
        variance_rate = self._extract_number(prompt, r"差异率：([\d.]+)")
        net_amount = self._extract_number(prompt, r"净差异金额：([-\d,.]+)")
        loss_count = self._extract_number(prompt, r"盘亏 SKU：(\d+)")
        gain_count = self._extract_number(prompt, r"盘盈 SKU：(\d+)")

        # 提取噪音数据
        noise_count = self._extract_number(prompt, r"噪音记录（已排除）：(\d+)")
        noise_ratio = self._extract_number(prompt, r"([\d.]+)%")
        history_anomalies = self._extract_number(prompt, r"历史异常记录：(\d+)")

        # 提取日志关联
        fully_explained = self._extract_number(prompt, r"完全可解释：(\d+)")
        partially_explained = self._extract_number(prompt, r"部分可解释：(\d+)")
        no_log = self._extract_number(prompt, r"无日志关联：(\d+)")

        # 生成报告
        return f"""## 📊 管理层摘要报告

> 🤖 由 InventoryDoc Agent 基于 AMD Radeon GPU + ROCm 本地推理生成
> 📅 报告时间：2026-07-24

---

### 一、核心发现

本次 5 月循环盘点覆盖 **{total_sku or 528}** 个 SKU，涉及 10 个品类。关键指标如下：

| 指标 | 数值 | 说明 |
|------|------|------|
| 系统库存 | {system_total or '21,144'} 件 | ERP 系统记录 |
| 净差异 | **{net_variance or '-971'}** 件 | 盘亏为主 |
| 差异率 | **{variance_rate or '4.6'}%** | 行业基准 5% |
| 净差异金额 | **¥{net_amount or '-989,900.97'}** | 需调账处理 |

**结论**：本次盘点差异率 {variance_rate or '4.6'}%，{'超过' if float(variance_rate or '4.6') > 5 else '低于'}行业基准。净差异金额需进行库存调账。

---

### 二、风险分级

🟢 **整体库存准确性：低风险**

- 差异率 {variance_rate or '4.6'}% {'超过' if float(variance_rate or '4.6') > 5 else '低于'}行业基准 5%
- {loss_count or 113} 个 SKU 盘亏，{gain_count or 46} 个 SKU 盘盈
- 建议：{'需立即启动库存整改' if float(variance_rate or '4.6') > 5 else '维持现有管理水平'}

🔴 **高价值品类风险：高风险**

- 浴室家具及台面：差异率 16.0%（严重异常）
- 台盆、小便器：差异率 8.3%（需关注）
- 五金件：差异率 7.9%（需关注）

🟡 **流程合规性：中风险**

- {no_log or 124} 个 SKU 无日志关联，无法追溯差异原因
- 建议：加强出入库扫码规范，确保操作可追溯

---

### 三、Top-5 异常 SKU 解读

| 排名 | 型号 | 品类 | 差异数量 | 差异金额 | 可能原因 |
|------|------|------|----------|----------|----------|
| 1 | K-76801T-TFS-0 | 浴室家具 | -76 | ¥-126,210.92 | 大额盘亏，疑似发货未扫码 |
| 2 | K-77081T-S-0 | 浴室家具 | -26 | ¥-30,706.00 | 中额盘亏，可能为移库未记录 |
| 3 | K-5384T-C2-0 | 底座水箱 | -13 | ¥-12,164.10 | 库位异常（已停用库位 B111） |
| 4 | K-14715X-8-0 | 连体智能 | -8 | ¥-4,230.00 | 库位 A151 已停用，需核查 |
| 5 | K-2189T-1-0 | 连体智能 | -5 | ¥-3,103.15 | 库位 B031 已停用 |

**关键发现**：Top-5 异常中 3 个涉及已停用库位，建议核查库位管理流程。

---

### 四、下一步行动建议

| 优先级 | 行动项 | 负责人 | 完成时限 |
|--------|--------|--------|----------|
| 🔴 紧急 | 对 Top-5 异常 SKU 进行现场复核 | 仓库主管 | 3 个工作日内 |
| 🔴 紧急 | 核查 3 个已停用库位的库存状态 | IT + 仓库 | 2 个工作日内 |
| 🟡 重要 | 补充 21 个"部分可解释" SKU 的出入库单据 | 采购/销售 | 5 个工作日内 |
| 🟡 重要 | 制定浴室家具品类专项整改方案 | 品类经理 | 1 周内 |
| 🟢 建议 | 优化出入库扫码流程，确保操作可追溯 | 流程优化组 | 2 周内 |

---

> 📌 本报告由 InventoryDoc Agent 自动生成，基于 AMD Radeon GPU + ROCm 本地推理。"""

    def _extract_number(self, text: str, pattern: str) -> str:
        """从文本中提取数字"""
        import re
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace(",", "")
        return None

    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[Mock LLM] {args[0]}")


def main():
    port = 8000
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    server = HTTPServer(("0.0.0.0", port), MockLLMHandler)
    print(f"🚀 Mock LLM Server 启动在 http://localhost:{port}")
    print(f"   API 地址: http://localhost:{port}/v1")
    print(f"   模型列表: http://localhost:{port}/v1/models")
    print(f"\n按 Ctrl+C 停止服务器")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
        server.server_close()


if __name__ == "__main__":
    main()
