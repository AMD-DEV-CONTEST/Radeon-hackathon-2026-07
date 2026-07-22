# 示例知识库文档

在此目录下放置你的私有文档，Agent 会自动索引这些文档用于 RAG 检索。

支持的文件格式：
- `.txt` 纯文本文件
- `.md` Markdown 文件
- `.pdf` PDF 文件（需要额外安装 PyPDF2）

## 示例文件说明

### 三单交叉校验示例
- `po_sample.txt` - 采购订单样本（PO-2026-001）
- `delivery_sample.txt` - 送货单样本（DN-2026-001）- 与PO匹配
- `delivery_sample_mismatch.txt` - 送货单样本（DN-2026-002）- 数量差异
- `invoice_sample.txt` - 发票样本（INV-2026-001）- 与PO匹配

### 演示流程
1. 先上传 `po_sample.txt` 处理采购订单
2. 上传 `delivery_sample.txt` 进行三单校验（匹配）
3. 上传 `delivery_sample_mismatch.txt` 演示异常检测
4. 上传 `invoice_sample.txt` 完成三单校验

## 使用方式

1. 将文档放入 `data/sample_docs/` 目录
2. 启动 Agent 后，在 Web UI 的"知识库管理"标签页上传更多文档
3. 在对话中提问，Agent 会自动从知识库中检索相关信息

## 示例问题

- "这个项目的核心功能是什么？"
- "如何部署这个系统？"
- "支持哪些 AMD GPU 型号？"
- "这个采购订单的供应商是谁？"
- "送货单的数量与采购订单匹配吗？"
