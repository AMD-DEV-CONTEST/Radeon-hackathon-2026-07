# -*- coding: utf-8 -*-
"""
app.py — 智能理赔 Agent 前端（Gradio Chat 对话式交互）

从原「按钮两步固定流水」升级为对话驱动的 Agent 交互：
- 上传发票图片 + 文本提问；
- 确定性流水线（agent/pipeline.py）逐阶段流式展示进度，作为主审核动作，金额可复核；
- 右侧结论卡片展示总额 / 可报 / 逐项明细；
- 纯文本追问走 answer_followup（复用会话记忆中的结构化结果，对齐设计文档 4.4 / 8.1）；
- 多轮会话按 session_id 隔离。

支持两种审核模式（两个 Tab 共享同一 session_state）：
- 单张审核：上传一张发票图片，逐阶段流式审核；
- 批量审核：上传整个文件夹，逐张流式审核并跨发票聚合得出批量理赔结论，可导出 CSV。
"""

import os
import uuid
import tempfile

import gradio as gr

import agent  # noqa: F401  注入 sys.path
import config as cfg
from agent.pipeline import process_invoice_stream, format_result_text, format_decision_card
from agent.agent import answer_followup, stream_followup
from agent.batch_pipeline import process_batch_stream, list_images
from tools.export_tool import export_batch_csv
from agent.memory import get_store

WELCOME = (
    "你好，我是**智能理赔审核助手**。\n\n"
    "- 上传一张发票图片并点击发送，我会依次完成：**多模态识别 → 真伪查验 → 药品目录检索 → 理赔金额计算**，"
    "并在右侧给出结论卡片；\n"
    "- 之后你可以直接追问，例如「为什么某药被拒？」「按乙类重算是多少？」，我会基于本次审核结果回答。"
)

BATCH_WELCOME = (
    "你好，这里是**批量发票审核**模式。\n\n"
    "- 在左侧「选择发票图片文件夹」处上传一个包含多张发票图片的文件夹（或按住 Ctrl 多选文件）；\n"
    "- 勾选「调用官方真伪查验接口」后点击「开始批量审核」，我会逐张完成 "
    "**OCR 识别 → 重复检测 → 真伪查验 → 药品目录检索 → 理赔决策**，并跨发票聚合得出批量结论；\n"
    "- 审核过程中左侧对话气泡会实时展示每张发票的处理进度；\n"
    "- 审核完成后，右侧会展示批量汇总卡片，点击「导出 CSV」可下载明细表格；\n"
    "- 重复发票会自动跳过查验与决策，仅计入计数。"
)


def _new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def _render_streaming_bubble(reasoning_text: str, content_text: str) -> str:
    """把流式追问的思考过程与正文渲染为气泡内容。

    思考过程非空时，用 <details> 折叠灰色块包裹，置于正文之前；正文用 Markdown。
    两者都为空时返回占位「🤔 思考中…」。
    """
    if not reasoning_text and not content_text:
        return "🤔 思考中…"
    if reasoning_text:
        return (
            f"<details style='color:#888;font-size:12px;'>"
            f"<summary>💭 思考过程</summary>"
            f"<div style='padding:6px 10px;white-space:pre-wrap;'>{reasoning_text}</div>"
            f"</details>\n\n{content_text}"
        )
    return content_text


def respond(message, image, do_verify, history, session_id):
    """对话主处理：有图走确定性流水线（流式），无图走记忆追问。"""
    history = history or []
    if not session_id:
        session_id = _new_session_id()

    message = (message or "").strip()

    # 无输入：不处理
    if not message and not image:
        yield history, gr.update(), message, image, session_id
        return

    # 追加用户气泡
    if image:
        user_display = (message + "\n\n📎 已上传发票图片，开始审核…").strip()
    else:
        user_display = message
    history.append({"role": "user", "content": user_display})
    history.append({"role": "assistant", "content": ""})

    # 先清空输入框与图片（图片路径已在局部变量中保留）
    if image:
        # ---- 有图：确定性理赔流水线（逐阶段流式展示）----
        final = {}
        status_log = []
        for ev in process_invoice_stream(image, do_verify=bool(do_verify), session_id=session_id):
            if ev.get("status"):
                status_log.append(ev["status"])
                history[-1]["content"] = "\n\n".join(status_log)
                yield history, gr.update(), "", None, session_id
            elif ev.get("done"):
                final = ev["result"]

        summary = format_result_text(final)
        card = format_decision_card(final)
        history[-1]["content"] = summary
        yield history, card, "", None, session_id
    else:
        # ---- 无图：流式追问（思考过程 + 正文，基于会话记忆三级回退）----
        history[-1]["content"] = "🤔 思考中…"
        yield history, gr.update(), "", None, session_id
        reasoning_parts = []
        content_parts = []
        for ev in stream_followup(message, session_id=session_id):
            t = ev.get("type")
            if t == "reasoning":
                reasoning_parts.append(ev.get("text", ""))
            elif t == "content":
                content_parts.append(ev.get("text", ""))
            elif t == "error":
                content_parts.append(f"\n\n⚠️ {ev.get('text', '')}")
                break
            # done 或其他：跳过
            history[-1]["content"] = _render_streaming_bubble(
                "".join(reasoning_parts), "".join(content_parts))
            yield history, gr.update(), "", None, session_id


def clear_session():
    """开始新会话：清空对话、卡片，并分配新的 session_id。"""
    return [], "", "", None, _new_session_id()


def clear_batch_session():
    """批量审核 Tab 的新会话：清空批量对话、批量卡片，并分配新的 session_id。

    返回 3 元组，对应批量 Tab 的输出 [chatbot_batch, card_batch, session_state]。
    """
    return [], "", _new_session_id()


# 批量理赔结论配色：与 pipeline._CONCLUSION_STYLE 同款风格，但在 app.py 内部本地定义，
# 不从 pipeline 导入私有常量，以保持模块封装。映射批量结论 → 图标/背景/前景色。
_BATCH_CONCLUSION_STYLE = {
    "全部通过": ("✅", "#e6f4ea", "#137333"),
    "部分通过": ("⚠️", "#fef7e0", "#b06000"),
    "全部拒赔": ("❌", "#fce8e6", "#c5221f"),
}


def format_batch_card(batch_result) -> str:
    """把批量结果渲染为右侧卡片（Markdown/HTML），供批量 Tab 右侧展示。返回字符串。

    结构：
    - 空/失败结果 → 错误提示 div（参考 format_decision_card 失败分支风格）；
    - 整体结论色块（图标 + 批量理赔结论 + 计数副行）；
    - 金额汇总表（价税合计总额 / 可报销合计 / 医保 / 商保 / 封顶后医保）；
    - 逐张明细表（序号/文件名/发票号/价税合计/医保可报/商保可报/可报合计/结论）；
      成功且非重复的发票行下方紧跟一行逐项药品明细子表（药品/金额/类别/医保可报/商保可报/理由）；
    - 封顶触发时附 cap_note 说明。
    所有字段均做 .get 防御。
    """
    # 空结果或失败：错误提示 div
    if not batch_result or not batch_result.get("ok"):
        msg = ""
        if isinstance(batch_result, dict):
            msg = batch_result.get("message", "") or batch_result.get("stage", "")
        tail = f"：{msg}" if msg else ""
        return (f"<div style='padding:12px;border-radius:8px;background:#fce8e6;color:#c5221f;'>"
                f"❌ 批量处理失败{tail}</div>")

    aggregate = batch_result.get("aggregate", {}) or {}
    conclusion = aggregate.get("conclusion", "")
    icon, bg, fg = _BATCH_CONCLUSION_STYLE.get(conclusion, ("ℹ️", "#e8f0fe", "#1a73e8"))

    total_invoices = aggregate.get("total_invoices", 0)
    success_count = aggregate.get("success_count", 0)
    failed_count = aggregate.get("failed_count", 0)
    duplicate_count = aggregate.get("duplicate_count", 0)

    total_amount = aggregate.get("total_amount", 0.0)
    total_reimbursable = aggregate.get("total_reimbursable", 0.0)
    total_medical = aggregate.get("total_medical_insurance", 0.0)
    total_commercial = aggregate.get("total_commercial", 0.0)
    cap_applied = bool(aggregate.get("cap_applied", False))
    medical_after_cap = aggregate.get("medical_after_cap", total_medical)
    cap_note = aggregate.get("cap_note", "")

    # 金额汇总表（Markdown）
    amount_rows = (
        f"| 价税合计总额 | {total_amount} |\n"
        f"| **可报销合计** | **{total_reimbursable}** |\n"
        f"| └ 医保报销 | {total_medical} |\n"
        f"| └ 商保报销 | {total_commercial} |"
    )
    if cap_applied:
        amount_rows += f"\n| └ 封顶后医保 | {medical_after_cap} |"

    # 逐张明细表（HTML table）
    detail_rows = ""
    for inv in batch_result.get("invoices", []) or []:
        if not isinstance(inv, dict):
            continue
        # 序号：index + 1，防御非整型
        idx = inv.get("index", "")
        try:
            seq = int(idx) + 1
        except (TypeError, ValueError):
            seq = idx
        filename = inv.get("filename", "")
        ok = bool(inv.get("ok", False))
        duplicate_of = inv.get("duplicate_of", None)
        stage = inv.get("stage", "")

        extract = inv.get("extract")
        if not isinstance(extract, dict):
            extract = {}
        fphm = extract.get("fphm", "")
        code = extract.get("code", "")  # 价税合计

        decision = inv.get("decision")
        if not isinstance(decision, dict):
            decision = {}
        med = decision.get("total_medical_insurance", "")
        com = decision.get("total_commercial", "")
        reimb = decision.get("total_reimbursable", "")
        inv_conc = decision.get("conclusion", "")

        # 结论列：重复 > 失败 > 成功
        if duplicate_of is not None:
            cell_conc = "重复 ⚠️"
        elif not ok:
            cell_conc = f"失败（{stage}）"
        else:
            cell_conc = inv_conc

        detail_rows += (
            f"<tr>"
            f"<td style='text-align:center'>{seq}</td>"
            f"<td>{filename}</td>"
            f"<td>{fphm}</td>"
            f"<td style='text-align:right'>{code}</td>"
            f"<td style='text-align:right'>{med}</td>"
            f"<td style='text-align:right'>{com}</td>"
            f"<td style='text-align:right'>{reimb}</td>"
            f"<td style='text-align:center'>{cell_conc}</td>"
            f"</tr>"
        )

        # 成功且非重复的发票：在主表行下方展开该发票的逐项药品明细子表。
        # 重复发票（duplicate_of 非 None）与失败发票（ok=False）的 decision 为 None，跳过。
        if ok and duplicate_of is None:
            items = decision.get("items")
            # 防御：items 非列表或为空列表时直接跳过，不输出子表
            if isinstance(items, list) and items:
                item_rows = ""
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    item_rows += (
                        f"<tr>"
                        f"<td>{it.get('name', '')}</td>"
                        f"<td style='text-align:right'>{it.get('amount', 0)}</td>"
                        f"<td style='text-align:center'>{it.get('category', '')}</td>"
                        f"<td style='text-align:right'>{it.get('medical_reimbursable', 0)}</td>"
                        f"<td style='text-align:right'>{it.get('commercial_reimbursable', 0)}</td>"
                        f"<td>{it.get('reason', '')}</td>"
                        f"</tr>"
                    )
                # 子表列与单张 format_decision_card 对齐（药品/金额/类别/医保可报/商保可报），并增加"理由"列
                detail_rows += (
                    f"<tr><td colspan='8'>"
                    f"<div style='padding-left:18px;font-size:11px;color:#666;'>└ 药品明细</div>"
                    f"<table style='width:95%;margin-left:18px;font-size:11px;"
                    f"background:#f9f9f9;border-radius:4px;'>"
                    f"<thead><tr>"
                    f"<th align='left'>药品</th>"
                    f"<th>金额</th>"
                    f"<th>类别</th>"
                    f"<th>医保可报</th>"
                    f"<th>商保可报</th>"
                    f"<th align='left'>理由</th>"
                    f"</tr></thead>"
                    f"<tbody>{item_rows}</tbody>"
                    f"</table>"
                    f"</td></tr>"
                )

    # 封顶提示
    cap_section = ""
    if cap_applied and cap_note:
        cap_section = (
            f"<div style='margin-top:8px;padding:8px 10px;border-radius:6px;"
            f"background:#fef7e0;color:#b06000;font-size:12px;'>⚠️ {cap_note}</div>"
        )

    return f"""<div style='padding:14px 16px;border-radius:10px;background:{bg};color:{fg};'>
  <div style='font-size:20px;font-weight:700;'>{icon} 批量理赔结论：{conclusion}</div>
  <div style='margin-top:6px;font-size:13px;color:#444;'>
    共 {total_invoices} 张（成功 {success_count}、失败 {failed_count}、重复 {duplicate_count}）
  </div>
</div>

### 💰 金额汇总

| 项目 | 金额(元) |
|------|--------:|
{amount_rows}

### 📋 逐张明细

<table style='width:100%;font-size:12px;'>
<thead><tr>
<th align='center'>序号</th>
<th align='left'>文件名</th>
<th align='left'>发票号</th>
<th>价税合计</th>
<th>医保可报</th>
<th>商保可报</th>
<th>可报合计</th>
<th align='center'>结论</th>
</tr></thead>
<tbody>{detail_rows}</tbody>
</table>
{cap_section}
"""


def respond_batch(files, do_verify, history, session_id):
    """批量流式处理生成器：更新对话气泡进度 + 右侧批量卡片。

    入参 files 为 gr.File(file_count="directory") 返回的文件路径列表（可能为 None/空）。
    输出列表 = [chatbot_batch, card_batch, session_state]（3 个输出，不清空文件输入）。
    """
    history = history or []
    if not session_id:
        session_id = _new_session_id()

    # 用 list_images 展开为有序图片路径列表（files 可能是单 str 路径或列表，list_images 都能处理）
    image_paths = list_images(files or [])
    if not image_paths:
        history.append({"role": "user", "content": "📎 已上传文件夹，但未找到发票图片"})
        exts = "、".join(str(e) for e in getattr(cfg, "IMAGE_EXTS", []))
        history.append({
            "role": "assistant",
            "content": (f"⚠️ 未在所选文件夹中找到支持的发票图片文件"
                        + (f"（支持格式：{exts}）" if exts else "")
                        + "，请重新选择包含发票图片的文件夹后再试。"),
        })
        yield history, gr.update(), session_id
        return

    # 追加用户气泡 + 空助手气泡
    history.append({"role": "user", "content": f"📎 已上传 {len(image_paths)} 张发票图片，开始批量审核…"})
    history.append({"role": "assistant", "content": ""})

    status_log = []
    final = {}
    for ev in process_batch_stream(image_paths, do_verify=bool(do_verify), session_id=session_id):
        if ev.get("status"):
            status_log.append(ev["status"])
            history[-1]["content"] = "\n\n".join(status_log)
            yield history, gr.update(), session_id
        elif ev.get("done"):
            final = ev.get("result", {}) or {}

    aggregate = (final or {}).get("aggregate", {}) or {}
    summary = aggregate.get("summary_text", "批量审核完成。")
    history[-1]["content"] = summary
    card = format_batch_card(final)
    yield history, card, session_id


def respond_batch_followup(message, history, session_id):
    """批量 Tab 追问流式处理生成器：消费 stream_followup，更新批量对话气泡。

    输出 4 元组 [chatbot_batch, card_batch, msg_batch, session_state]：
    - chatbot_batch 流式更新（思考+正文）；
    - card_batch 保持不变（gr.update()）；
    - msg_batch 清空（gr.update(value="")）；
    - session_state 透传。
    """
    history = history or []
    if not session_id:
        session_id = _new_session_id()
    message = (message or "").strip()
    if not message:
        yield history, gr.update(), gr.update(), session_id
        return
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": "🤔 思考中…"})
    yield history, gr.update(), gr.update(), session_id
    reasoning_parts = []
    content_parts = []
    for ev in stream_followup(message, session_id=session_id):
        t = ev.get("type")
        if t == "reasoning":
            reasoning_parts.append(ev.get("text", ""))
        elif t == "content":
            content_parts.append(ev.get("text", ""))
        elif t == "error":
            content_parts.append(f"\n\n⚠️ {ev.get('text', '')}")
            break
        history[-1]["content"] = _render_streaming_bubble(
            "".join(reasoning_parts), "".join(content_parts))
        yield history, gr.update(), gr.update(), session_id


def export_csv_handler(session_id):
    """导出 CSV 按钮点击处理：将会话中的批量结果导出为临时 CSV 文件，返回文件路径。

    - 无 session_id 或无批量结果 → 返回 None 并 print 警告；
    - 异常时返回 None。
    """
    try:
        if not session_id:
            print("[export_csv_handler] session_id 为空，无法导出")
            return None
        batch = get_store().get_batch_claim(session_id)
        if not batch:
            print(f"[export_csv_handler] 未找到会话 {session_id} 的批量结果，请先执行批量审核")
            return None
        csv_text = export_batch_csv(batch)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            prefix=f"batch_claims_{session_id}_",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(csv_text)
            return f.name
    except Exception as e:
        print(f"[export_csv_handler] 导出 CSV 失败：{e}")
        return None


CSS = """
.card-box { min-height: 120px; }
footer { display: none !important; }
"""

with gr.Blocks(title="智能理赔 Agent") as demo:
    gr.Markdown("# 🏥 智能理赔 Agent 系统")
    gr.Markdown(
        "多模态发票识别 · 官方真伪查验 · RAG 药品目录检索 · 确定性理赔决策 · 支持单张/批量审核　"
        "｜　后端：AMD ROCm + Qwen 多模态大模型"
    )

    session_state = gr.State(value="")

    with gr.Tabs():
        with gr.Tab("单张审核"):
            with gr.Row():
                with gr.Column(scale=3):
                    chatbot = gr.Chatbot(
                        label="对话",
                        height=460,
                        value=[{"role": "assistant", "content": WELCOME}],
                    )
                    with gr.Row():
                        image_input = gr.Image(type="filepath", label="发票图片", height=140)
                        with gr.Column():
                            msg = gr.Textbox(
                                label="消息",
                                placeholder="上传发票后点击发送开始审核；或直接输入问题追问…",
                                lines=3,
                            )
                            do_verify = gr.Checkbox(
                                value=False,
                                label="调用官方真伪查验接口（关闭则为演示模式，跳过外部查验）",
                            )
                            with gr.Row():
                                send_btn = gr.Button("发送", variant="primary")
                                clear_btn = gr.Button("新会话")

                with gr.Column(scale=2):
                    gr.Markdown("### 📊 理赔结论卡片")
                    card = gr.Markdown(value="", elem_classes=["card-box"])

            outputs = [chatbot, card, msg, image_input, session_state]
            send_btn.click(
                fn=respond,
                inputs=[msg, image_input, do_verify, chatbot, session_state],
                outputs=outputs,
            )
            msg.submit(
                fn=respond,
                inputs=[msg, image_input, do_verify, chatbot, session_state],
                outputs=outputs,
            )
            clear_btn.click(fn=clear_session, inputs=None, outputs=outputs)

        with gr.Tab("批量审核"):
            with gr.Row():
                with gr.Column(scale=3):
                    chatbot_batch = gr.Chatbot(
                        label="批量对话",
                        height=460,
                        value=[{"role": "assistant", "content": BATCH_WELCOME}],
                    )
                    with gr.Row():
                        file_input = gr.File(
                            label="选择发票图片文件夹（或按住 Ctrl 多选文件）",
                            file_count="directory",
                            file_types=["image"],
                        )
                        with gr.Column():
                            do_verify_b = gr.Checkbox(
                                value=False,
                                label="调用官方真伪查验接口（关闭为演示模式）",
                            )
                            with gr.Row():
                                batch_btn = gr.Button("开始批量审核", variant="primary")
                                export_btn = gr.Button("导出 CSV")
                                clear_btn_b = gr.Button("新会话")
                    with gr.Row():
                        msg_batch = gr.Textbox(
                            label="追问（批量审核完成后可在此提问）",
                            placeholder="如「这批总共能报多少」「哪几张被拒了」…",
                            lines=2,
                            scale=4,
                        )
                        send_btn_batch = gr.Button("发送追问", variant="primary", scale=1)

                with gr.Column(scale=2):
                    gr.Markdown("### 📊 批量理赔汇总")
                    card_batch = gr.Markdown(value="", elem_classes=["card-box"])
                    csv_file = gr.File(label="CSV 下载", visible=False)

            batch_btn.click(
                fn=respond_batch,
                inputs=[file_input, do_verify_b, chatbot_batch, session_state],
                outputs=[chatbot_batch, card_batch, session_state],
            )
            send_btn_batch.click(
                fn=respond_batch_followup,
                inputs=[msg_batch, chatbot_batch, session_state],
                outputs=[chatbot_batch, card_batch, msg_batch, session_state],
            )
            msg_batch.submit(
                fn=respond_batch_followup,
                inputs=[msg_batch, chatbot_batch, session_state],
                outputs=[chatbot_batch, card_batch, msg_batch, session_state],
            )
            export_btn.click(
                fn=export_csv_handler,
                inputs=[session_state],
                outputs=csv_file,
            )
            clear_btn_b.click(
                fn=clear_batch_session,
                inputs=None,
                outputs=[chatbot_batch, card_batch, session_state],
            )

    demo.load(fn=_new_session_id, inputs=None, outputs=session_state)


def _warmup():
    """后台预热：提前加载嵌入模型与检索器，避免首次上传时 RAG 阶段冷启动卡顿。"""
    try:
        from rag.retriever import get_retriever
        get_retriever().search("预热")
    except Exception as e:
        print(f"[WARN] 预热失败（不影响使用，首次检索会稍慢）：{e}")


# Gradio 6 网络自检补丁（此环境 DNS 不通，跳过内网可达性检查）
import httpx
_orig_get = httpx.get
def _patched_get(url, **kw):
    try:
        return _orig_get(url, **kw)
    except Exception:
        class _Dummy:
            is_success = True
        return _Dummy()
httpx.get = _patched_get
import gradio.networking as gnet
gnet.url_ok = lambda url: True

if __name__ == "__main__":
    import threading
    threading.Thread(target=_warmup, daemon=True).start()
    demo.queue(default_concurrency_limit=4)
    demo.launch(server_name="0.0.0.0", server_port=7865, share=False)
