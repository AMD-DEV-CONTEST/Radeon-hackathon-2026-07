"""
UI — 供应链单据处理 Web 界面。
提供单据上传、自动处理、校验结果展示、对话查询功能。
"""

import gradio as gr
import json


def create_ui(agent):
    """创建 Gradio Web UI。"""

    def process_single_doc(file):
        """处理单张单据。"""
        if file is None:
            return "请上传文件", "", ""

        content = Path(file.name).read_text(encoding="utf-8")
        result = agent.process_document(content, file.name)

        fields_json = json.dumps(result["extracted_fields"], ensure_ascii=False, indent=2)
        status = f"单据类型: {result['doc_type']}\n状态: {result['status']}"
        rag_info = result.get("rag_context", "无相关案例")

        return status, fields_json, rag_info

    def cross_validate_docs(po_file, delivery_file, invoice_file):
        """三单交叉校验。"""
        docs = []
        for f, expected_type in [
            (po_file, "purchase_order"),
            (delivery_file, "delivery_note"),
            (invoice_file, "invoice"),
        ]:
            if f is not None:
                content = Path(f.name).read_text(encoding="utf-8")
                result = agent.process_document(content, f.name)
                docs.append(result)

        if len(docs) < 2:
            return "请至少上传两种单据进行交叉校验", ""

        validation = agent.cross_validate(docs)
        status = "✅ 全部通过" if validation["all_pass"] else "❌ 存在异常"
        details = json.dumps(validation["details"], ensure_ascii=False, indent=2)
        return status, details

    def chat(user_message, history):
        response = agent.query(user_message)
        history = history or []
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response})
        return history, ""

    with gr.Blocks(title="Supply Chain DocAgent", theme=gr.themes.Soft()) as ui:
        gr.Markdown(
            "# Supply Chain DocAgent\n"
            "*基于 AMD Radeon GPU + ROCm 的供应链单据智能处理系统*"
        )

        with gr.Tabs():
            with gr.TabItem("单据处理"):
                gr.Markdown("### 上传单张单据进行自动识别和提取")
                doc_file = gr.File(label="上传单据", file_types=[".txt", ".md", ".pdf"])
                process_btn = gr.Button("开始处理", variant="primary")

                with gr.Row():
                    with gr.Column():
                        doc_status = gr.Textbox(label="处理状态", lines=3)
                    with gr.Column():
                        doc_fields = gr.Textbox(label="提取字段 (JSON)", lines=8)
                    with gr.Column():
                        doc_rag = gr.Textbox(label="参考案例", lines=3)

                process_btn.click(
                    process_single_doc, [doc_file],
                    [doc_status, doc_fields, doc_rag]
                )

            with gr.TabItem("三单校验"):
                gr.Markdown("### 上传 PO + 送货单 + 发票 进行交叉校验")
                with gr.Row():
                    po_file = gr.File(label="采购订单 (PO)", file_types=[".txt", ".md"])
                    delivery_file = gr.File(label="送货单", file_types=[".txt", ".md"])
                    invoice_file = gr.File(label="发票", file_types=[".txt", ".md"])

                validate_btn = gr.Button("开始校验", variant="primary")
                validation_status = gr.Textbox(label="校验结果", lines=2)
                validation_details = gr.Textbox(label="校验详情 (JSON)", lines=10)

                validate_btn.click(
                    cross_validate_docs, [po_file, delivery_file, invoice_file],
                    [validation_status, validation_details]
                )

            with gr.TabItem("智能问答"):
                chatbot = gr.Chatbot(height=500, label="对话窗口")
                with gr.Row():
                    msg_input = gr.Textbox(placeholder="询问供应链单据相关问题...", scale=8)
                    send_btn = gr.Button("发送", variant="primary", scale=1)
                send_btn.click(chat, [msg_input, chatbot], [chatbot, msg_input])
                msg_input.submit(chat, [msg_input, chatbot], [chatbot, msg_input])

        return ui


from pathlib import Path
