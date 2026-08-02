"""SparkFencer Blade Pose Studio — local frame labelling, training and testing.

Run with:
    python webui/blade_studio.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import gradio as gr

from fencing_analysis.blade_pose_dataset import (
    BladeAnnotation, dataset_summary, ensure_dataset, evaluate_pose_model,
    extract_video_frames, label_path_for, list_images, load_annotations,
    render_annotations, save_annotations, start_training,
)

CSS = """
:root { --ink:#080b10; --panel:#111720; --panel2:#171f2a; --line:#2a3441; --text:#edf1f5; --muted:#93a0ae; --orange:#ff7417; --cyan:#16c6d2; --green:#35bb79; }
body,.gradio-container { background:var(--ink)!important; color:var(--text)!important; }
.gradio-container { max-width:1680px!important; padding:0 22px 28px!important; font-family:"IBM Plex Sans","Noto Sans SC",system-ui,sans-serif!important; }
.studio-header { display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px 4px 16px;border-bottom:1px solid var(--line);margin-bottom:16px; }
.studio-brand { color:#f5f7fa;font-size:25px;font-weight:750;font-style:italic;letter-spacing:-.8px; }.studio-brand b{color:var(--orange)}.studio-brand em{color:var(--cyan);font-style:inherit}
.studio-status{color:var(--muted);font-size:12px}.studio-status strong{color:#9ae7be}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 12px rgba(53,187,121,.7);margin-right:6px}
.studio-layout{gap:14px!important;align-items:stretch!important}.rail,.inspector,.bottom-panel{background:var(--panel)!important;border:1px solid var(--line)!important;border-radius:12px!important;padding:14px!important}.canvas{background:#070a0f!important;border:1px solid var(--line)!important;border-radius:12px!important;padding:12px!important}
.step{display:flex;align-items:center;gap:9px;color:var(--text);font-size:14px;font-weight:650;margin:9px 0 14px}.step span{width:25px;height:25px;border:1px solid var(--orange);border-radius:50%;color:var(--orange);display:inline-flex;justify-content:center;align-items:center;font-size:12px}.hint{font-size:12px;color:var(--muted);line-height:1.55}.title{font-size:13px;font-weight:700;letter-spacing:.04em;color:#dce3ea;margin:2px 0 9px}.privacy{border-left:3px solid var(--green);background:#0d1816;color:#b8dfc8;border-radius:4px 8px 8px 4px;padding:10px 11px;font-size:12px;line-height:1.55;margin-bottom:14px}.privacy b{color:#e1fae9}
.gr-button-primary{background:var(--orange)!important;border:0!important;color:#fff!important;font-weight:700!important;min-height:42px!important}.gr-button-secondary{background:#25303d!important;border:1px solid #384657!important;color:#e1e8ee!important}.gr-input,textarea,input,select{background:#0c1118!important;border-color:#33404f!important;color:var(--text)!important}label span,.block-label{color:#bac5d1!important;font-size:12px!important}.bottom-panel{margin-top:14px}.bottom-panel .wrap{gap:10px!important}footer{display:none!important}@media(max-width:900px){.gradio-container{padding:0 10px 20px!important}.studio-header{align-items:flex-start;flex-direction:column;gap:8px}.studio-layout{flex-direction:column!important}}
"""

HEADER = """
<div class="studio-header"><div class="studio-brand">Spark<b>Fen</b><em>cer</em> · 剑尖数据工坊</div><div class="studio-status"><span class="dot"></span><strong>本地标注、训练与评测</strong>　数据仅保存到当前工作区</div></div>
"""


def _state(dataset="datasets/blade_tip_pose", split="train", images=None, index=0, annotations=None):
    return {"dataset": dataset, "split": split, "images": images or [], "index": index, "annotations": annotations or []}


def _annotation_objects(state):
    return [BladeAnnotation(**ann) for ann in state.get("annotations", [])]


def _annotation_dicts(annotations):
    return [{"guard": a.guard, "tip": a.tip, "guard_visible": a.guard_visible, "tip_visible": a.tip_visible} for a in annotations]


def _current_image(state):
    images = state.get("images", [])
    index = state.get("index", 0)
    return images[index] if images and 0 <= index < len(images) else None


def _image_size(image_path):
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(image_path)
    h, w = image.shape[:2]
    return w, h


def _render_state(state, selected=0):
    image_path = _current_image(state)
    if not image_path:
        return None
    return render_annotations(image_path, _annotation_objects(state), selected)


def _summary_markdown(dataset):
    try:
        data = dataset_summary(dataset)
    except Exception as exc:
        return f"⚠️ 数据集状态不可用：{exc}"
    parts = [f"**{name}** {v['annotated']}/{v['images']} 帧 · {v['instances']} 把剑" for name, v in data["splits"].items()]
    total = data["total_images"] or 1
    return (f"### 数据集完成度\n\n{data['annotated_images']}/{data['total_images']} 帧已标注 "
            f"({data['annotated_images'] / total * 100:.1f}%) · {data['instances']} 个剑实例\n\n" + "　|　".join(parts))


def extract_frames_ui(video, dataset, split, every_n, max_frames):
    if not video:
        return "请先选择视频。", _summary_markdown(dataset)
    try:
        result = extract_video_frames(video, dataset, split, int(every_n), int(max_frames))
        return (f"✅ 已抽取 **{result['written']}** 帧到 `{result['dataset']}/images/{split}`。"
                f"视频帧率：{result['fps']:.2f}。", _summary_markdown(dataset))
    except Exception as exc:
        return f"❌ 抽帧失败：`{exc}`", _summary_markdown(dataset)


def load_split_ui(dataset, split):
    try:
        ensure_dataset(dataset)
        images = list_images(dataset, split)
        state = _state(dataset, split, images=images)
        if not images:
            return gr.update(value=[]), None, state, "当前分区没有帧。请先在“抽帧”页导入视频。", _summary_markdown(dataset)
        image_path = images[0]
        w, h = _image_size(image_path)
        state["annotations"] = _annotation_dicts(load_annotations(label_path_for(image_path, dataset, split), w, h))
        return gr.update(value=images, selected_index=0), _render_state(state), state, f"已载入 {len(images)} 帧。点击画布依次设置护手与剑尖。", _summary_markdown(dataset)
    except Exception as exc:
        return gr.update(value=[]), None, _state(dataset, split), f"❌ 无法读取数据集：{exc}", _summary_markdown(dataset)


def select_gallery_ui(state, evt: gr.SelectData):
    images = state.get("images", [])
    index = int(evt.index if not isinstance(evt.index, tuple) else evt.index[0])
    if not images or not 0 <= index < len(images):
        return None, state, "未选择有效帧。"
    state = dict(state, index=index)
    image_path = images[index]
    w, h = _image_size(image_path)
    state["annotations"] = _annotation_dicts(load_annotations(label_path_for(image_path, state["dataset"], state["split"]), w, h))
    return _render_state(state), state, f"帧 {index + 1}/{len(images)}：{Path(image_path).name}"


def canvas_click_ui(state, selected_index, point_kind, evt: gr.SelectData):
    image_path = _current_image(state)
    if not image_path:
        return None, state, "请先载入数据集帧。"
    annotations = _annotation_objects(state)
    selected = max(0, min(int(selected_index or 0), len(annotations)))
    if selected == len(annotations):
        annotations.append(BladeAnnotation())
    x, y = map(float, evt.index[:2])
    target = annotations[selected]
    if point_kind == "guard":
        target.guard = (x, y)
    else:
        target.tip = (x, y)
    state = dict(state, annotations=_annotation_dicts(annotations))
    next_hint = "下一步：点击剑尖。" if point_kind == "guard" else "下一步：选择护手，或保存标注。"
    return _render_state(state, selected), state, f"已更新第 {selected + 1} 把剑的{'护手' if point_kind == 'guard' else '剑尖'}。{next_hint}"


def add_instance_ui(state):
    annotations = _annotation_objects(state)
    annotations.append(BladeAnnotation())
    state = dict(state, annotations=_annotation_dicts(annotations))
    return _render_state(state, len(annotations) - 1), state, len(annotations) - 1, "已新增一把剑；先选择“护手”，再点击画布。"


def delete_instance_ui(state, selected_index):
    annotations = _annotation_objects(state)
    if annotations and 0 <= int(selected_index or 0) < len(annotations):
        annotations.pop(int(selected_index or 0))
    selected = max(0, min(int(selected_index or 0), max(0, len(annotations) - 1)))
    state = dict(state, annotations=_annotation_dicts(annotations))
    return _render_state(state, selected), state, selected, "已删除选中的剑实例。"


def save_ui(state):
    image_path = _current_image(state)
    if not image_path:
        return state, "请先选择帧。", _summary_markdown(state.get("dataset", "datasets/blade_tip_pose"))
    try:
        w, h = _image_size(image_path)
        count = save_annotations(label_path_for(image_path, state["dataset"], state["split"]),
                                 _annotation_objects(state), w, h)
        return state, f"✅ 已保存 `{Path(image_path).name}`：{count} 把完整标注。", _summary_markdown(state["dataset"])
    except Exception as exc:
        return state, f"❌ 保存失败：{exc}", _summary_markdown(state["dataset"])


def move_frame_ui(state, delta):
    images = state.get("images", [])
    if not images:
        return None, state, "没有可切换的帧。"
    index = int(max(0, min(len(images) - 1, state.get("index", 0) + delta)))
    state = dict(state, index=index)
    path = images[index]
    w, h = _image_size(path)
    state["annotations"] = _annotation_dicts(load_annotations(label_path_for(path, state["dataset"], state["split"]), w, h))
    return _render_state(state), state, f"帧 {index + 1}/{len(images)}：{Path(path).name}"


def train_ui(dataset, model, epochs, imgsz, batch, device):
    try:
        info = start_training(dataset, model=model, epochs=int(epochs), imgsz=int(imgsz), batch=int(batch), device=device)
        cmd = " ".join(info["command"])
        return f"✅ 本地训练已启动（PID {info['pid']}）。\n\n日志：`{info['log_path']}`\n\n```bash\n{cmd}\n```"
    except Exception as exc:
        return f"❌ 无法启动训练：`{exc}`"


def evaluate_ui(model, dataset, split, conf, imgsz, device):
    if not model:
        return "请先提供训练产出的 `best.pt` 路径。"
    try:
        result = evaluate_pose_model(model, dataset, split=split, conf=float(conf), imgsz=int(imgsz), device=device)
        return ("## 剑尖评测结果\n\n"
                f"- 检出率：**{result['detection_rate'] * 100:.1f}%** ({result['matched_instances']}/{result['ground_truth_instances']})\n"
                f"- 剑尖平均误差：**{result['tip_mean_pixel_error']} px**\n"
                f"- 剑尖中位误差：**{result['tip_median_pixel_error']} px**\n"
                f"- PCK@5 px：**{result['tip_pck_at_5px'] * 100:.1f}%**\n"
                f"- PCK@10 px：**{result['tip_pck_at_10px'] * 100:.1f}%**\n\n"
                f"结果已写入 `{result['report_path']}`。")
    except Exception as exc:
        return f"❌ 评测失败：`{exc}`"


def build_app():
    theme = gr.themes.Soft(primary_hue="orange", secondary_hue="cyan", neutral_hue="slate")
    with gr.Blocks(title="SparkFencer 剑尖数据工坊", theme=theme, css=CSS) as demo:
        gr.HTML(HEADER)
        dataset = gr.Textbox(value="datasets/blade_tip_pose", label="本地数据集目录（所有操作共用）")
        summary = gr.Markdown(_summary_markdown("datasets/blade_tip_pose"), elem_classes="bottom-panel")
        with gr.Tabs():
            with gr.Tab("① 抽帧"):
                with gr.Row(elem_classes="studio-layout"):
                    with gr.Column(scale=1, elem_classes="rail"):
                        gr.HTML('<div class="step"><span>1</span>导入源视频</div><p class="hint">从目标域视频稀疏抽帧，优先保留突刺、交叉剑、遮挡和运动模糊场景。</p>')
                        source_video = gr.Video(label="视频", sources=["upload"])
                    with gr.Column(scale=2, elem_classes="canvas"):
                        gr.HTML('<div class="title">抽帧配置</div>')
                        extract_split = gr.Radio(["train", "val", "test"], value="train", label="写入分区")
                        stride = gr.Slider(1, 120, value=15, step=1, label="每 N 帧抽一张")
                        max_frames = gr.Slider(0, 2000, value=0, step=10, label="最多抽取帧数（0=不限）")
                        extract_button = gr.Button("抽取可标注帧", variant="primary")
                        extract_status = gr.Markdown()
                    with gr.Column(scale=1, elem_classes="inspector"):
                        gr.HTML('<div class="privacy"><b>本地数据集</b><br>视频帧和标签只写入当前工作区，不上传到任何服务。</div><div class="title">建议</div><p class="hint">首轮每个视频每 10–20 帧取一张。不要随机拆分同一视频的相邻帧到验证集。</p>')
                extract_button.click(extract_frames_ui, [source_video, dataset, extract_split, stride, max_frames], [extract_status, summary])

            with gr.Tab("② 标注"):
                with gr.Row(elem_classes="studio-layout"):
                    with gr.Column(scale=1, min_width=210, elem_classes="rail"):
                        gr.HTML('<div class="step"><span>1</span>选择数据分区</div>')
                        annotation_split = gr.Radio(["train", "val", "test"], value="train", label="分区")
                        load_button = gr.Button("载入帧序列", variant="secondary")
                        gr.HTML('<hr><div class="step"><span>2</span>点选关键点</div><p class="hint">每把剑：先点护手中心，再点真实剑尖。若同帧两把剑，新增实例后重复标注。</p>')
                        point_kind = gr.Radio([("护手", "guard"), ("剑尖", "tip")], value="guard", label="当前点击写入")
                        previous_button = gr.Button("← 上一帧", variant="secondary")
                        next_button = gr.Button("下一帧 →", variant="secondary")
                    with gr.Column(scale=3, min_width=520, elem_classes="canvas"):
                        gr.HTML('<div class="title">主画布 · 点击精确标注护手与剑尖</div>')
                        canvas = gr.Image(label="标注画布", interactive=False)
                        annotation_status = gr.Markdown("载入帧序列后开始标注。")
                        frame_gallery = gr.Gallery(label="帧序列", columns=7, height=130, object_fit="cover")
                    with gr.Column(scale=1, min_width=250, elem_classes="inspector"):
                        gr.HTML('<div class="privacy"><b>标注规则</b><br>剑尖必须是剑刃的最远可见端。看不清的帧宁可不保存，也不要猜测。</div><div class="title">实例属性</div>')
                        selected_instance = gr.Number(value=0, precision=0, label="当前剑实例（从 0 开始）")
                        add_button = gr.Button("+ 新增一把剑", variant="secondary")
                        delete_button = gr.Button("删除当前实例", variant="secondary")
                        save_button = gr.Button("保存标注", variant="primary")
                        annotation_state = gr.State(_state())

                load_button.click(load_split_ui, [dataset, annotation_split], [frame_gallery, canvas, annotation_state, annotation_status, summary])
                frame_gallery.select(select_gallery_ui, [annotation_state], [canvas, annotation_state, annotation_status])
                canvas.select(canvas_click_ui, [annotation_state, selected_instance, point_kind], [canvas, annotation_state, annotation_status])
                add_button.click(add_instance_ui, [annotation_state], [canvas, annotation_state, selected_instance, annotation_status])
                delete_button.click(delete_instance_ui, [annotation_state, selected_instance], [canvas, annotation_state, selected_instance, annotation_status])
                save_button.click(save_ui, [annotation_state], [annotation_state, annotation_status, summary])
                previous_button.click(lambda s: move_frame_ui(s, -1), [annotation_state], [canvas, annotation_state, annotation_status])
                next_button.click(lambda s: move_frame_ui(s, 1), [annotation_state], [canvas, annotation_state, annotation_status])

            with gr.Tab("③ 训练"):
                with gr.Group(elem_classes="bottom-panel"):
                    gr.Markdown("## 本地 YOLO Pose 训练\n模型学习每把剑的 `guard → blade_tip` 两个关键点；训练日志和权重保存在本地 `runs/blade_pose/`。")
                    with gr.Row():
                        train_model = gr.Textbox(value="yolo11s-pose.pt", label="初始化权重")
                        train_epochs = gr.Slider(20, 400, value=200, step=10, label="Epochs")
                        train_imgsz = gr.Dropdown([640, 960, 1280, 1536], value=1280, label="训练尺寸")
                        train_batch = gr.Slider(1, 32, value=4, step=1, label="Batch")
                        train_device = gr.Textbox(value="0", label="设备")
                    train_button = gr.Button("开始本地训练", variant="primary")
                    train_status = gr.Markdown()
                    train_button.click(train_ui, [dataset, train_model, train_epochs, train_imgsz, train_batch, train_device], [train_status])

            with gr.Tab("④ 评测"):
                with gr.Group(elem_classes="bottom-panel"):
                    gr.Markdown("## 留出集剑尖精度评测\n以人工关键点为真值，报告检出率、剑尖像素误差与 PCK@5 / PCK@10。请使用从未参与训练的视频作为测试集。")
                    with gr.Row():
                        eval_model = gr.Textbox(label="best.pt 路径", placeholder="runs/blade_pose/.../weights/best.pt", scale=3)
                        eval_split = gr.Radio(["val", "test"], value="test", label="评测分区")
                        eval_conf = gr.Slider(0.05, 0.8, value=0.15, step=0.05, label="置信度阈值")
                        eval_imgsz = gr.Dropdown([640, 960, 1280, 1536], value=1280, label="推理尺寸")
                        eval_device = gr.Textbox(value="0", label="设备")
                    eval_button = gr.Button("运行评测", variant="primary")
                    eval_status = gr.Markdown()
                    eval_button.click(evaluate_ui, [eval_model, dataset, eval_split, eval_conf, eval_imgsz, eval_device], [eval_status])
    return demo


if __name__ == "__main__":
    build_app().launch(server_name="0.0.0.0", server_port=7861, show_error=True)
