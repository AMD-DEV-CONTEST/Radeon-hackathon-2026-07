"""Tiny Screen-AI desktop pet.

Lightweight Tkinter companion for checking whether the local agent understands
commands. It previews plans through /command/preview and never executes actions.
"""

from __future__ import annotations

import json
import threading
import time
import tkinter as tk
from tkinter import ttk
from urllib.error import URLError
from urllib.request import Request, urlopen


API_BASE = "http://localhost:8000"


class ScreenPet:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Screen-AI Pet")
        self.root.geometry("320x390+80+120")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0b141a")
        self.root.resizable(False, False)

        self.drag_x = 0
        self.drag_y = 0
        self.mood = "idle"
        self.tick = 0

        self._build()
        self._animate()

    def _build(self) -> None:
        self.header = tk.Frame(self.root, bg="#202c33", height=42)
        self.header.pack(fill="x")
        self.header.bind("<ButtonPress-1>", self._drag_start)
        self.header.bind("<B1-Motion>", self._drag_move)

        tk.Label(
            self.header,
            text="Screen-AI Pet",
            bg="#202c33",
            fg="#e9edef",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left", padx=10)
        tk.Button(
            self.header,
            text="x",
            bg="#202c33",
            fg="#8696a0",
            bd=0,
            command=self.root.destroy,
            font=("Segoe UI", 11, "bold"),
        ).pack(side="right", padx=8)

        self.canvas = tk.Canvas(self.root, width=180, height=150, bg="#0b141a", highlightthickness=0)
        self.canvas.pack(pady=(16, 4))

        self.bubble = tk.Label(
            self.root,
            text="Type a command. I will preview the plan.",
            bg="#202c33",
            fg="#d1d7db",
            wraplength=270,
            justify="left",
            padx=12,
            pady=10,
            font=("Segoe UI", 9),
        )
        self.bubble.pack(fill="x", padx=14, pady=8)

        self.input = tk.Text(
            self.root,
            height=3,
            bg="#2a3942",
            fg="#e9edef",
            insertbackground="#e9edef",
            bd=0,
            padx=10,
            pady=8,
            font=("Segoe UI", 9),
        )
        self.input.pack(fill="x", padx=14, pady=(4, 8))
        self.input.insert("1.0", "open gx browser and go to youtube.com")

        buttons = tk.Frame(self.root, bg="#0b141a")
        buttons.pack(fill="x", padx=14)
        ttk.Button(buttons, text="Preview", command=self.preview).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(buttons, text="Clear", command=self.clear).pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.status = tk.Label(
            self.root,
            text="local preview only",
            bg="#0b141a",
            fg="#8696a0",
            font=("Segoe UI", 8),
        )
        self.status.pack(fill="x", padx=14, pady=(8, 0))

    def _drag_start(self, event) -> None:
        self.drag_x = event.x
        self.drag_y = event.y

    def _drag_move(self, event) -> None:
        x = self.root.winfo_x() + event.x - self.drag_x
        y = self.root.winfo_y() + event.y - self.drag_y
        self.root.geometry(f"+{x}+{y}")

    def clear(self) -> None:
        self.input.delete("1.0", "end")
        self._say("Ready for another command.", "idle")

    def preview(self) -> None:
        text = self.input.get("1.0", "end").strip()
        if not text:
            self._say("Give me something to understand first.", "idle")
            return
        self._say("Thinking through the plan...", "thinking")
        threading.Thread(target=self._preview_worker, args=(text,), daemon=True).start()

    def _preview_worker(self, text: str) -> None:
        try:
            payload = json.dumps({"text": text}).encode("utf-8")
            req = Request(
                f"{API_BASE}/command/preview",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
            steps = data.get("plan", {}).get("steps", [])
            step_text = "\n".join(
                f"{idx + 1}. {step.get('tool')} {step.get('args', {})}"
                for idx, step in enumerate(steps[:4])
            )
            message = (
                f"Intent: {data.get('intent')}\n"
                f"Risk: {data.get('risk_level')} | Steps: {len(steps)}\n"
                f"{step_text or data.get('message', 'No executable plan yet.')}"
            )
            self.root.after(0, lambda: self._say(message, "happy"))
        except URLError:
            self.root.after(0, lambda: self._say("Backend is offline. Start Screen-AI first.", "sad"))
        except Exception as exc:
            self.root.after(0, lambda: self._say(f"Preview failed: {exc}", "sad"))

    def _say(self, text: str, mood: str) -> None:
        self.mood = mood
        self.bubble.config(text=text)
        self.status.config(text=f"{mood} | {time.strftime('%I:%M %p')}")
        self._draw_pet()

    def _animate(self) -> None:
        self.tick += 1
        self._draw_pet()
        self.root.after(650, self._animate)

    def _draw_pet(self) -> None:
        c = self.canvas
        c.delete("all")
        bounce = 4 if self.tick % 2 else 0
        body = "#00a884" if self.mood != "sad" else "#ef4444"
        accent = "#25d366" if self.mood == "happy" else "#8696a0"
        c.create_oval(34, 22 + bounce, 146, 132 + bounce, fill=body, outline="")
        c.create_oval(56, 56 + bounce, 74, 74 + bounce, fill="#06261f", outline="")
        c.create_oval(106, 56 + bounce, 124, 74 + bounce, fill="#06261f", outline="")
        if self.mood == "thinking":
            c.create_arc(68, 78 + bounce, 112, 112 + bounce, start=200, extent=140, width=3, outline="#06261f")
            c.create_text(154, 28, text="...", fill=accent, font=("Segoe UI", 14, "bold"))
        elif self.mood == "sad":
            c.create_arc(68, 92 + bounce, 112, 122 + bounce, start=20, extent=140, width=3, outline="#06261f")
        else:
            c.create_arc(68, 76 + bounce, 112, 106 + bounce, start=200, extent=140, width=3, outline="#06261f")
        c.create_oval(76, 128 + bounce, 104, 138 + bounce, fill="#202c33", outline="")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    ScreenPet().run()
