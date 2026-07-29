"""Doubao-like studio chat UI for Jupyter (no tunnel).

Light workspace: sidebar apps · suggestion chips · bottom composer with tools.
"""

from __future__ import annotations

from html import escape
from typing import Any, Callable

from src.apps.modes import APP_MODES


SHELL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@500;700&family=Noto+Sans+SC:wght@400;500;700&display=swap');
.pla-studio {
  --bg: #f4f6f8;
  --panel: #ffffff;
  --line: #e6ebf0;
  --text: #1f2329;
  --muted: #8a9199;
  --accent: #0f766e;
  --accent-soft: #ccfbf1;
  --chip: #f0f3f6;
  font-family: "Noto Sans SC", "DM Sans", "Segoe UI", sans-serif;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 18px;
  overflow: hidden;
  min-height: 640px;
  display: grid;
  grid-template-columns: 220px 1fr;
}
.pla-side {
  background: var(--panel);
  border-right: 1px solid var(--line);
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pla-brand {
  font-family: "DM Sans", sans-serif;
  font-weight: 700;
  font-size: 20px;
  letter-spacing: -0.03em;
  padding: 8px 10px 14px;
}
.pla-brand small {
  display: block;
  font-size: 11px;
  color: var(--muted);
  font-weight: 500;
  margin-top: 2px;
}
.pla-nav {
  border: 0;
  background: transparent;
  text-align: left;
  padding: 10px 12px;
  border-radius: 10px;
  color: var(--text);
  font-size: 13px;
  cursor: default;
}
.pla-nav.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
}
.pla-main {
  display: flex;
  flex-direction: column;
  min-height: 640px;
  background:
    radial-gradient(900px 320px at 50% -10%, rgba(15,118,110,.08), transparent 55%),
    var(--bg);
}
.pla-top {
  padding: 14px 20px;
  border-bottom: 1px solid var(--line);
  background: rgba(255,255,255,.72);
  backdrop-filter: blur(8px);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.pla-top h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
.pla-top span { color: var(--muted); font-size: 12px; }
.pla-stage {
  flex: 1;
  overflow: auto;
  padding: 28px 24px 12px;
}
.pla-hero {
  text-align: center;
  padding: 48px 12px 24px;
}
.pla-hero h1 {
  margin: 0 0 10px;
  font-size: 34px;
  letter-spacing: -0.04em;
  font-weight: 700;
}
.pla-hero p { margin: 0; color: var(--muted); font-size: 14px; }
.pla-chips {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  max-width: 720px;
  margin: 22px auto 0;
}
.pla-chip {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 13px;
  color: #334155;
  text-align: left;
}
.pla-chat { max-width: 820px; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }
.pla-row { display: flex; }
.pla-row.user { justify-content: flex-end; }
.pla-row.bot { justify-content: flex-start; }
.pla-bubble {
  max-width: 78%;
  padding: 12px 14px;
  border-radius: 16px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
}
.pla-bubble.user {
  background: var(--accent);
  color: #ecfdf5;
  border-bottom-right-radius: 4px;
}
.pla-bubble.bot {
  background: var(--panel);
  border: 1px solid var(--line);
  border-bottom-left-radius: 4px;
}
.pla-meta { margin-top: 8px; color: var(--muted); font-size: 12px; }
.pla-composer-wrap {
  padding: 10px 18px 18px;
}
.pla-composer {
  max-width: 860px;
  margin: 0 auto;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 12px 12px 10px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, .04);
}
.pla-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}
.pla-tool {
  background: var(--chip);
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  color: #475569;
}
@media (max-width: 860px) {
  .pla-studio { grid-template-columns: 1fr; }
  .pla-side { display: none; }
}
</style>
"""


def render_shell(
    *,
    mode_id: str,
    mode_title: str,
    history: list[dict[str, Any]],
    suggestions: list[str],
) -> str:
    nav = []
    for m in APP_MODES:
        cls = "pla-nav active" if m.id == mode_id else "pla-nav"
        nav.append(f'<div class="{cls}">{escape(m.title)}</div>')
    if not history:
        chips = "".join(f'<div class="pla-chip">{escape(s)}</div>' for s in suggestions[:6])
        stage = f"""
        <div class="pla-hero">
          <h1>有什么我能帮你的吗？</h1>
          <p>PrivateLocalAgent · {escape(mode_title)} · 本地 Radeon 推理</p>
        </div>
        <div class="pla-chips">{chips}</div>
        """
    else:
        rows = []
        for t in history:
            rows.append(
                f'<div class="pla-row user"><div class="pla-bubble user">{escape(t.get("q",""))}</div></div>'
            )
            rows.append(
                "<div class='pla-row bot'><div class='pla-bubble bot'>"
                f"{escape(t.get('a',''))}"
                f"<div class='pla-meta'>{escape(t.get('meta',''))}</div>"
                "</div></div>"
            )
        stage = f'<div class="pla-chat">{"".join(rows)}</div>'

    tools = "".join(
        f'<span class="pla-tool">{escape(x)}</span>'
        for x in ["本地RAG", "工作流", "记忆", "企业合规", "开发技能", "多代理"]
    )
    return f"""
{SHELL_CSS}
<div class="pla-studio">
  <aside class="pla-side">
    <div class="pla-brand">PrivateLocalAgent<small>Track 2 · 私有本地 Agent</small></div>
    <div class="pla-nav active">新对话</div>
    <div class="pla-nav">新办公任务</div>
    <div style="height:8px"></div>
    {''.join(nav)}
  </aside>
  <section class="pla-main">
    <div class="pla-top">
      <h2>{escape(mode_title)}</h2>
      <span>AI 生成内容请注意甄别 · 无隧道</span>
    </div>
    <div class="pla-stage">{stage}</div>
    <div class="pla-composer-wrap">
      <div class="pla-composer">
        <div style="color:#94a3b8;font-size:13px;padding:4px 6px 10px">在下方输入框发消息…</div>
        <div class="pla-tools">{tools}</div>
      </div>
    </div>
  </section>
</div>
"""


def launch_studio(
    orch: Any,
    skills: Any,
    *,
    on_status: Callable[[str], None] | None = None,
) -> None:
    """Interactive Doubao-like UI using ipywidgets + HTML shell."""
    import ipywidgets as w
    from IPython.display import clear_output, display

    history: list[dict[str, Any]] = []
    mode_opts = [f"{m.id} | {m.title}" for m in APP_MODES]
    skill_opts = [f"{s['id']} | {s['title']}" for s in skills.list_skills()]

    def mode_id_from(label: str) -> str:
        return label.split("|")[0].strip()

    def mode_title(mid: str) -> str:
        for m in APP_MODES:
            if m.id == mid:
                return m.title
        return mid

    def suggestions(mid: str) -> list[str]:
        for m in APP_MODES:
            if m.id == mid:
                return list(m.demo_prompts)
        return ["请假需要提前几天申请？"]

    mid0 = "multi"
    shell = w.HTML(value=render_shell(mode_id=mid0, mode_title=mode_title(mid0), history=history, suggestions=suggestions(mid0)))
    mode_dd = w.Dropdown(options=mode_opts, value=[x for x in mode_opts if x.startswith("multi")][0], description="应用")
    tips = w.ToggleButtons(options=suggestions(mid0))
    q = w.Textarea(value=tips.options[0], placeholder="发消息…", layout=w.Layout(width="100%", height="78px"))
    skill_dd = w.Dropdown(options=skill_opts, description="技能")
    proj = w.Text(value="my_demo", description="项目名")
    send = w.Button(description="发送", button_style="primary")
    skill_btn = w.Button(description="运行技能生成项目")
    new_btn = w.Button(description="新对话")
    status = w.HTML("<span style='color:#8a9199'>就绪</span>")

    def redraw() -> None:
        mid = mode_id_from(mode_dd.value)
        shell.value = render_shell(
            mode_id=mid,
            mode_title=mode_title(mid),
            history=history,
            suggestions=list(tips.options),
        )

    def on_mode(change: dict[str, Any]) -> None:
        if change.get("name") != "value":
            return
        mid = mode_id_from(change["new"])
        tips.options = suggestions(mid)
        q.value = tips.options[0]
        redraw()

    def on_tip(change: dict[str, Any]) -> None:
        if change.get("name") == "value":
            q.value = change["new"]

    def on_new(_: Any) -> None:
        history.clear()
        redraw()
        status.value = "<span style='color:#8a9199'>已开新对话</span>"

    def on_skill(_: Any) -> None:
        sid = skill_dd.value.split("|")[0].strip()
        skill_btn.disabled = True
        status.value = "<span style='color:#0f766e'>正在生成项目…</span>"
        try:
            params = {"name": proj.value.strip()} if proj.value.strip() else {}
            result = skills.run(sid, params)
            history.append({"q": f"[技能] {sid}", "a": result.as_text(), "meta": "开发者生产力代理 · 已写盘"})
            redraw()
            status.value = f"<span style='color:#0f766e'>已生成 {escape(result.project_dir)}</span>"
        except Exception as exc:  # noqa: BLE001
            status.value = f"<span style='color:#b91c1c'>{escape(str(exc))}</span>"
        finally:
            skill_btn.disabled = False

    def on_send(_: Any) -> None:
        query = q.value.strip()
        if not query:
            return
        send.disabled = True
        status.value = "<span style='color:#0f766e'>思考中…</span>"
        try:
            mid = mode_id_from(mode_dd.value)
            r = orch.run(query, mode=mid)
            meta = f"{getattr(r,'specialist','Agent')} · {', '.join((r.used_tools or [])[:5])}"
            history.append({"q": query, "a": r.answer, "meta": meta})
            redraw()
            status.value = "<span style='color:#0f766e'>完成</span>"
            q.value = ""
        except Exception as exc:  # noqa: BLE001
            status.value = f"<span style='color:#b91c1c'>{escape(str(exc))}</span>"
        finally:
            send.disabled = False

    mode_dd.observe(on_mode, names="value")
    tips.observe(on_tip, names="value")
    send.on_click(on_send)
    skill_btn.on_click(on_skill)
    new_btn.on_click(on_new)

    clear_output(wait=True)
    display(
        shell,
        w.HBox([new_btn, mode_dd]),
        tips,
        w.HBox([skill_dd, proj, skill_btn]),
        q,
        w.HBox([send]),
        status,
    )
