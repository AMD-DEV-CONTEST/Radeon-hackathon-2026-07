"""CustomTkinter 主窗口 + 一键生成流程。"""
from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from content_studio.config import AppConfig, get_active_provider, load_config, save_config
from content_studio.core import exporter, image_pipeline, ocr
from content_studio.core.generator import Generator, build_material
from content_studio.core.models import LLMClient, LLMError

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, cfg: AppConfig, on_save):
        super().__init__(master)
        self.title("设置")
        self.geometry("520x560")
        self.cfg = cfg
        self.on_save = on_save
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="当前 Provider").pack(anchor="w", padx=16, pady=(16, 0))
        names = [p.name for p in self.cfg.providers]
        self.provider_var = ctk.StringVar(value=self.cfg.active_provider or (names[0] if names else ""))
        self.provider_menu = ctk.CTkOptionMenu(self, values=names, variable=self.provider_var)
        self.provider_menu.pack(fill="x", padx=16)

        ctk.CTkLabel(self, text="API Key").pack(anchor="w", padx=16, pady=(12, 0))
        self.key_entry = ctk.CTkEntry(self, show="*", width=480)
        self.key_entry.pack(fill="x", padx=16)
        cur = self._current_provider()
        if cur:
            self.key_entry.insert(0, cur.api_key)

        ctk.CTkLabel(self, text="模型名").pack(anchor="w", padx=16, pady=(12, 0))
        self.model_entry = ctk.CTkEntry(self, width=480)
        self.model_entry.pack(fill="x", padx=16)
        if cur:
            self.model_entry.insert(0, cur.model)

        ctk.CTkLabel(self, text="水印文字").pack(anchor="w", padx=16, pady=(12, 0))
        self.watermark_entry = ctk.CTkEntry(self, width=480)
        self.watermark_entry.pack(fill="x", padx=16)
        self.watermark_entry.insert(0, self.cfg.image.watermark_text)

        self.collage_var = ctk.BooleanVar(value=self.cfg.image.collage)
        ctk.CTkCheckBox(self, text="小红书封面用 collage 拼图", variable=self.collage_var).pack(anchor="w", padx=16, pady=(8, 0))

        self.ocr_var = ctk.BooleanVar(value=self.cfg.ocr_enabled)
        ctk.CTkCheckBox(self, text="启用 OCR（从图片提取文字）", variable=self.ocr_var).pack(anchor="w", padx=16)

        ctk.CTkButton(self, text="保存", command=self._save).pack(pady=16)

    def _current_provider(self):
        for p in self.cfg.providers:
            if p.name == self.provider_var.get():
                return p
        return self.cfg.providers[0] if self.cfg.providers else None

    def _save(self):
        p = self._current_provider()
        if p:
            p.api_key = self.key_entry.get()
            p.model = self.model_entry.get()
        self.cfg.active_provider = self.provider_var.get()
        self.cfg.image.watermark_text = self.watermark_entry.get()
        self.cfg.image.collage = self.collage_var.get()
        self.cfg.ocr_enabled = self.ocr_var.get()
        save_config(self.cfg)
        self.on_save(self.cfg)
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Content Studio")
        self.geometry("1100x720")
        self.cfg = load_config()
        self.image_paths: list[str] = []
        self._build()
        # 首次启动若没有任何 provider 配过 api_key，自动弹设置面板
        if not any(p.api_key for p in self.cfg.providers):
            self.after(100, self._open_settings)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        ctk.CTkLabel(top, text="Content Studio", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left", padx=8)
        ctk.CTkButton(top, text="设置", width=80, command=self._open_settings).pack(side="right", padx=4)
        self.gen_btn = ctk.CTkButton(top, text="一键生成", width=120, command=self._on_generate)
        self.gen_btn.pack(side="right", padx=4)

        # 左：输入
        left = ctk.CTkFrame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=6)
        left.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(left, text="素材文字").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        self.text_box = ctk.CTkTextbox(left)
        self.text_box.grid(row=2, column=0, sticky="nsew", padx=10, pady=6)
        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.grid(row=1, column=0, sticky="ew", padx=10)
        ctk.CTkButton(btns, text="添加图片", command=self._add_images).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btns, text="清空图片", command=self._clear_images).pack(side="left")
        self.img_label = ctk.CTkLabel(left, text="未选择图片", anchor="w")
        self.img_label.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))

        # 右：输出（tab）
        right = ctk.CTkFrame(self)
        right.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=6)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        self.tabs = ctk.CTkTabview(right)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        self.tabs.add("公众号")
        self.tabs.add("小红书")
        self.wechat_box = ctk.CTkTextbox(self.tabs.tab("公众号"))
        self.wechat_box.pack(fill="both", expand=True, padx=6, pady=6)
        self.xhs_box = ctk.CTkTextbox(self.tabs.tab("小红书"))
        self.xhs_box.pack(fill="both", expand=True, padx=6, pady=6)

        bar = ctk.CTkFrame(right, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        self.status = ctk.CTkLabel(bar, text="就绪", anchor="w")
        self.status.pack(side="left")
        ctk.CTkButton(bar, text="复制公众号", width=110, command=lambda: self._copy(self.wechat_box)).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="复制小红书", width=110, command=lambda: self._copy(self.xhs_box)).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="打开输出目录", width=120, command=self._open_output).pack(side="right", padx=4)
        # 第二阶段入口：灰置
        self.pub_btn = ctk.CTkButton(bar, text="发布到公众号(未启用)", width=160, state="disabled")
        self.pub_btn.pack(side="right", padx=4)

    # ---- 输入 ----
    def _add_images(self):
        files = filedialog.askopenfilenames(filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp")])
        if not files:
            return
        MAX_IMAGES = 9
        room = MAX_IMAGES - len(self.image_paths)
        if room <= 0:
            messagebox.showwarning("图片数量超限", f"最多 {MAX_IMAGES} 张图片。")
            return
        adding = list(files[:room])
        if len(files) > room:
            messagebox.showwarning("图片数量超限", f"最多 {MAX_IMAGES} 张图片，已保留前 {MAX_IMAGES} 张。")
        self.image_paths.extend(adding)
        self._refresh_img_label()

    def _clear_images(self):
        self.image_paths = []
        self._refresh_img_label()

    def _refresh_img_label(self):
        self.img_label.configure(text=f"已选 {len(self.image_paths)} 张图片" if self.image_paths else "未选择图片")

    # ---- 设置 ----
    def _open_settings(self):
        SettingsDialog(self, self.cfg, on_save=lambda c: setattr(self, "cfg", c))

    # ---- 生成 ----
    def _on_generate(self):
        provider = get_active_provider(self.cfg)
        if not provider.api_key:
            messagebox.showwarning("缺少配置", "请先在「设置」里填写当前 provider 的 API Key。")
            return
        # 在主线程快照所有 UI 状态，避免工作线程直接触碰 Tk 控件。
        user_text = self.text_box.get("1.0", "end-1c").strip()
        cfg = self.cfg
        image_paths = list(self.image_paths)
        self.gen_btn.configure(state="disabled")
        self.status.configure(text="生成中…")
        threading.Thread(
            target=self._generate_thread,
            args=(provider, user_text, cfg, image_paths),
            daemon=True,
        ).start()

    def _generate_thread(self, provider, user_text, cfg, image_paths):
        try:
            ocr_text = ""
            if cfg.ocr_enabled and image_paths:
                ocr_text = ocr.extract_text(image_paths)
            material = build_material(user_text, ocr_text, len(image_paths))

            client = LLMClient(provider)
            gen = Generator(client)
            wc_err = xh_err = None
            wechat = xhs = None
            try:
                wechat = gen.generate_wechat(material)
            except LLMError as e:
                wc_err = str(e)
            try:
                xhs = gen.generate_xhs(material)
            except LLMError as e:
                xh_err = str(e)

            # 逐张加载：坏图跳过并计数告警，不中断整批
            source_images = []
            skipped = 0
            for p in image_paths:
                try:
                    source_images.append(image_pipeline.load_image(p))
                except Exception:
                    skipped += 1

            out_dir = Path.cwd() / "output"
            art = exporter.export(wechat, xhs, source_images, cfg.image, out_dir)

            self._last_output_dir = art.out_dir
            self.after(0, lambda: self._render(wechat, xhs, wc_err, xh_err, skipped))
        except Exception as e:
            self.after(0, lambda: self._fail(str(e)))

    def _render(self, wechat, xhs, wc_err, xh_err, skipped=0):
        self.wechat_box.delete("1.0", "end")
        self.xhs_box.delete("1.0", "end")
        if wechat:
            self.wechat_box.insert("1.0", exporter.format_wechat(wechat))
        if wc_err:
            self.wechat_box.insert("1.0", f"⚠ 公众号生成失败：{wc_err}\n（可重新点「一键生成」重试）\n\n")
        if xhs:
            self.xhs_box.insert("1.0", exporter.format_xhs(xhs))
        if xh_err:
            self.xhs_box.insert("1.0", f"⚠ 小红书生成失败：{xh_err}\n（可重新点「一键生成」重试）\n\n")
        note = "完成"
        if skipped:
            note += f"（已跳过 {skipped} 张坏图）"
        self.status.configure(text=note)
        self.gen_btn.configure(state="normal")

    def _fail(self, msg):
        self.status.configure(text="出错")
        self.gen_btn.configure(state="normal")
        messagebox.showerror("出错", msg)

    # ---- 工具 ----
    def _copy(self, box: ctk.CTkTextbox):
        self.clipboard_clear()
        self.clipboard_append(box.get("1.0", "end-1c"))
        self.status.configure(text="已复制到剪贴板")

    def _open_output(self):
        d = getattr(self, "_last_output_dir", None)
        if d and Path(d).exists():
            import os
            os.startfile(str(d))   # type: ignore[attr-defined]
        else:
            messagebox.showinfo("提示", "还没有输出。先点「一键生成」。")


def run() -> None:
    App().mainloop()
