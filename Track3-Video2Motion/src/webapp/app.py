"""Video2Motion — one video in, a deployable humanoid control policy out.

    Step 1  Video  ->  SMPL-X body motion        GVHMR    AMD GPU
    Step 2  SMPL-X ->  Unitree G1 joints         GMR      CPU / IK
    Step 3  Reinforcement learning               MJX+PPO  AMD GPU
    Step 4  Physics rollout and comparison       MuJoCo   AMD GPU

Run:  python webapp/app.py          # serves on 0.0.0.0:7860
"""

import threading
import time
from pathlib import Path

import gradio as gr

import pipeline as P

N_STEPS = 4
TITLES = ["Extract Motion", "Retarget to G1", "Train Policy", "Simulate"]

CSS = """
:root { --v2s:#ED1C24; --v2s-soft:rgba(237,28,36,.10); }

.gradio-container{
  max-width:100% !important; width:100% !important;
  margin:0 auto !important; padding:0 26px 34px !important;
}
.main,.wrap,.contain{max-width:100% !important;}
footer{display:none !important;}

/* ── kill the loud red label pills that the red theme paints everywhere ── */
.block-label, .gradio-container label > span:first-child,
span[data-testid="block-info"]{
  background:transparent !important; border:none !important;
  color:var(--body-text-color-subdued) !important;
  font-weight:600 !important; font-size:12px !important;
  letter-spacing:.3px; padding:0 0 4px !important; box-shadow:none !important;
}
span[data-testid="block-info"]{font-weight:400 !important; opacity:.72;}

/* ── hero ── */
#hero{
  border-radius:14px; padding:18px 24px; margin:10px 0 14px;
  background:linear-gradient(120deg,#16181c 0%,#262a31 55%,#382226 100%);
  color:#fff; display:flex; align-items:center; gap:22px; flex-wrap:wrap;
}
#hero .t{flex:1 1 480px;}
#hero h1{margin:0 0 5px; font-size:23px; font-weight:700;}
#hero p{margin:0; opacity:.8; font-size:13.5px; line-height:1.55;}
#hero .chips{display:flex; gap:6px; flex-wrap:wrap;}
#hero .chip{
  font-size:11px; padding:3px 10px; border-radius:999px; white-space:nowrap;
  background:rgba(255,255,255,.10); border:1px solid rgba(255,255,255,.16);
}

/* ── stepper ── */
#stepper{display:flex; gap:9px; margin-bottom:13px;}
#stepper button{
  flex:1; min-width:0 !important; border-radius:10px !important;
  padding:11px 8px !important; font-size:13.5px !important;
  font-weight:600 !important;
  border:1px solid var(--border-color-primary) !important;
  background:var(--background-fill-secondary) !important;
  color:var(--body-text-color) !important;
}
#stepper button.on{
  border-color:var(--v2s) !important; background:var(--v2s-soft) !important;
  color:var(--v2s) !important;
}

/* ── panel ── */
.panel{
  border:1px solid var(--border-color-primary); border-radius:13px;
  padding:2px 18px 14px;
}
.phead{display:flex; align-items:baseline; gap:11px; margin:13px 0 2px;}
.phead .n{color:var(--v2s); font-weight:800; font-size:12.5px; letter-spacing:.7px;}
.phead .h{font-size:18px; font-weight:660;}
.phead .m{margin-left:auto; font-size:12px; opacity:.55; white-space:nowrap;}
.pdesc{font-size:13px; opacity:.74; margin:0 0 10px; line-height:1.55; max-width:960px;}

.note{
  font-size:12.5px; opacity:.85; border-left:3px solid var(--v2s);
  padding:8px 0 8px 11px; margin:10px 0 2px; background:var(--v2s-soft);
  border-radius:0 7px 7px 0; line-height:1.6;
}
.log-box textarea{
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace !important;
  font-size:11.5px !important; line-height:1.45 !important;
}
.metric-row{display:flex; gap:10px; flex-wrap:wrap; margin:8px 0 0;}
.metric{
  flex:1 1 150px; border:1px solid var(--border-color-primary);
  border-radius:10px; padding:10px 13px;
}
.metric .k{font-size:11px; opacity:.58; text-transform:uppercase; letter-spacing:.5px;}
.metric .v{font-size:20px; font-weight:700; margin-top:2px;}
.metric .u{font-size:11.5px; opacity:.55; font-weight:400; margin-left:3px;}

/* compact controls */
.side .block{margin-bottom:8px !important;}
#navrow{display:flex; gap:10px; margin-top:12px;}
#navrow button{border-radius:10px !important;}
.est{font-size:12.5px; opacity:.8; margin:-2px 0 6px;}
"""

HERO = """
<div id="hero">
  <div class="t">
    <h1>Video2Motion &nbsp;·&nbsp; Human Video to Humanoid Skill</h1>
    <p>Upload an ordinary video of a person moving; get a control policy the
       Unitree G1 can actually execute. The whole pipeline runs on an
       <b>AMD Radeon GPU with ROCm</b> — the mainstream stacks in this field
       (Isaac Lab, Isaac Sim, MuJoCo Warp) are CUDA-only.</p>
  </div>
  <div class="chips">
    <span class="chip">ROCm 7.2.1</span><span class="chip">Radeon Pro W7900</span>
    <span class="chip">MuJoCo MJX · JAX</span><span class="chip">Brax PPO</span>
    <span class="chip">4096 envs</span>
  </div>
</div>
"""


def phead(n, title, meta, desc):
    return (f'<div class="phead"><span class="n">STEP {n}</span>'
            f'<span class="h">{title}</span><span class="m">{meta}</span></div>'
            f'<p class="pdesc">{desc}</p>')


def metrics(items):
    cells = "".join(f'<div class="metric"><div class="k">{k}</div>'
                    f'<div class="v">{v}<span class="u">{u}</span></div></div>'
                    for k, v, u in items)
    return f'<div class="metric-row">{cells}</div>'


def curves(curve):
    if not curve:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [c["step"] / 1e6 for c in curve]
    spec = [("reward", "Episode return", "#ED1C24", "higher is better"),
            ("ep_len", "Episode length (steps)", "#e08e00", "higher is better"),
            ("body_pos", "Body position error (m)", "#2b6cb0", "lower is better"),
            ("body_ori", "Body orientation error (rad)", "#2f855a", "lower is better")]
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 5.8), dpi=110)
    for ax, (key, label, col, hint) in zip(axes.ravel(), spec):
        ax.plot(xs, [c[key] for c in curve], color=col, lw=2, marker="o", ms=3)
        ax.set_title(f"{label}   ({hint})", fontsize=10.5, loc="left")
        ax.set_xlabel("million env-steps", fontsize=9)
        ax.grid(alpha=.22, ls="--")
        ax.tick_params(labelsize=9)
    fig.tight_layout()
    return fig


def drive(job, fn, *args):
    threading.Thread(target=fn, args=(*args, job), daemon=True).start()
    while not job.done:
        yield job.tail()
        time.sleep(0.7)
    yield job.tail()


DL_HIDDEN = gr.update(visible=False)


def dl(path, label):
    return (gr.update(value=path, visible=True, label=label) if path
            else DL_HIDDEN)


# ══════════════════════════════════════════════════════════════════ UI
with gr.Blocks(title="Video2Motion") as demo:
    gr.HTML(HERO)

    cur = gr.State(0)
    s_name, s_pt, s_bm, s_params = (gr.State(""), gr.State(""),
                                    gr.State(""), gr.State(""))
    train_job = gr.State(None)

    with gr.Row(elem_id="stepper"):
        nav = [gr.Button(f"{i+1}.  {TITLES[i]}",
                         elem_classes=["on"] if i == 0 else [])
               for i in range(N_STEPS)]
    panels = []

    # ───────────────────────────────────────────────── STEP 1
    with gr.Group(visible=True, elem_classes="panel") as p1:
        gr.HTML(phead(1, "Extract human motion from video",
                      "GVHMR · AMD GPU · ~3 min",
                      "Estimates an SMPL-X body-motion sequence from a single "
                      "monocular video — no motion-capture rig, a phone "
                      "recording works. Name the project; every file produced "
                      "downstream inherits that name."))
        with gr.Row(equal_height=True):
            with gr.Column(scale=4, elem_classes="side"):
                in_name = gr.Textbox(
                    label="Project name",
                    placeholder="leave blank — you will be asked on Run",
                    info="Must be unique; every generated file inherits it")
                in_video = gr.Video(label="Input video", height=232)
                b1 = gr.Button("Run Step 1 — Extract motion", variant="primary")
                d1 = gr.DownloadButton("Download SMPL-X result", visible=False)
            with gr.Column(scale=6):
                out_smpl = gr.Video(label="SMPL-X pose estimate", height=330,
                                    interactive=False)
        log1 = gr.Textbox(label="Log", lines=8, max_lines=8,
                          elem_classes="log-box", interactive=False)
    panels.append(p1)

    # ───────────────────────────────────────────────── STEP 2
    with gr.Group(visible=False, elem_classes="panel") as p2:
        gr.HTML(phead(2, "Retarget to the Unitree G1", "GMR · CPU / IK · ~1 min",
                      "Maps the human pose onto the G1's 29 joints. Human and "
                      "robot differ in limb proportions and joint limits, so "
                      "this is an inverse-kinematics problem, not a copy."))
        with gr.Row(equal_height=True):
            with gr.Column(scale=4, elem_classes="side"):
                src2 = gr.Dropdown(label="Source",
                                   info="From Step 1, or an earlier result",
                                   choices=P.list_smpl(), allow_custom_value=True)
                with gr.Row():
                    r2 = gr.Button("↻ Refresh", scale=1)
                    b2 = gr.Button("Run Step 2 — Retarget", variant="primary",
                                   scale=3)
                d2 = gr.DownloadButton("Download G1 trajectory", visible=False)
                gr.HTML('<div class="note"><b>Why Step 3 exists.</b> What comes '
                        'out here is a <b>joint-angle animation</b>: it records '
                        'the <i>result</i> of a pose, not the <i>control effort</i> '
                        'that holds it. Replayed inside a physics engine the robot '
                        'falls over immediately.</div>')
            with gr.Column(scale=6):
                out_retarget = gr.Video(
                    label="Retargeted motion — kinematic replay, no physics",
                    height=330, interactive=False)
        log2 = gr.Textbox(label="Log", lines=8, max_lines=8,
                          elem_classes="log-box", interactive=False)
    panels.append(p2)

    # ───────────────────────────────────────────────── STEP 3
    with gr.Group(visible=False, elem_classes="panel") as p3:
        gr.HTML(phead(3, "Train the control policy", "MJX + Brax PPO · AMD GPU",
                      "Learns a policy that follows the reference motion and "
                      "keeps its balance. The reward tracks 3-D position, "
                      "orientation and velocity of 14 body links; the episode "
                      "ends the moment tracking drifts, so standing still earns "
                      "nothing. Stop any time — checkpoints already on disk stay "
                      "usable."))
        with gr.Row(equal_height=True):
            with gr.Column(scale=4, elem_classes="side"):
                src3 = gr.Dropdown(label="Motion",
                                   info="From Step 2, or an earlier one",
                                   choices=P.list_motions(),
                                   allow_custom_value=True)
                hours = gr.Number(value=8, minimum=0.02, step=1,
                                  label="Training budget (hours)",
                                  info="No upper limit — a hard motion may need "
                                       "days. ~16,500 env-steps/s.")
                est = gr.Markdown(elem_classes="est")
                ck_every = gr.Number(value=5, minimum=0.5, step=1,
                                     label="Checkpoint every (million steps)",
                                     info="Every checkpoint is kept and included "
                                          "in the download")
                with gr.Row():
                    r3 = gr.Button("↻ Refresh", scale=1)
                    b3 = gr.Button("Start training", variant="primary", scale=2)
                    b3stop = gr.Button("Stop", variant="stop", scale=1)
                d3 = gr.DownloadButton("Download all checkpoints", visible=False)
            with gr.Column(scale=6):
                plot3 = gr.Plot(label="Training curves")
        log3 = gr.Textbox(label="Log", lines=9, max_lines=9,
                          elem_classes="log-box", interactive=False)
    panels.append(p3)

    # ───────────────────────────────────────────────── STEP 4
    with gr.Group(visible=False, elem_classes="panel") as p4:
        gr.HTML(phead(4, "Run it in physics", "MuJoCo · AMD GPU · ~1 min",
                      "Rolls the policy out in MuJoCo and renders the reference "
                      "beside what the robot actually does. This is full physics — contacts, "
                      "gravity, actuator dynamics. The visible shaking is the policy "
                      "actively balancing: the G1 is an inverted pendulum and its ankle roll joints are soft (kp=2)."))
        with gr.Row(equal_height=True):
            with gr.Column(scale=4, elem_classes="side"):
                mode4 = gr.Radio(["Pre-trained policy", "A run I trained"],
                                 value="Pre-trained policy", label="Policy source")
                preset = gr.Dropdown(label="Pre-trained motion",
                                     choices=list(P.presets().keys()),
                                     value=(list(P.presets().keys()) or [None])[0])
                run4 = gr.Dropdown(label="Training run", choices=P.list_runs(),
                                   allow_custom_value=True, visible=False)
                ck4 = gr.Dropdown(label="Checkpoint", choices=[],
                                  allow_custom_value=True, visible=False)
                with gr.Row():
                    r4 = gr.Button("↻ Refresh", scale=1)
                    b4 = gr.Button("Run Step 4 — Simulate", variant="primary",
                                   scale=3)
                d4 = gr.DownloadButton("Download video", visible=False)
                stat4 = gr.HTML()
            with gr.Column(scale=6):
                out_sim = gr.Video(
                    label="Left: reference   |   Right: policy in MuJoCo MJX physics"
                          "  ·  not the unitree_mujoco DDS path",
                    height=380, interactive=False)
        log4 = gr.Textbox(label="Log", lines=8, max_lines=8,
                          elem_classes="log-box", interactive=False)
    panels.append(p4)

    with gr.Row(elem_id="navrow"):
        b_prev = gr.Button("←  Previous step")
        b_next = gr.Button("Next step  →", variant="primary")

    # ══════════════════════════════════════════ navigation
    def goto(i):
        i = max(0, min(N_STEPS - 1, int(i)))
        return ([i] + [gr.update(visible=(k == i)) for k in range(N_STEPS)]
                + [gr.update(elem_classes=["on"] if k == i else [])
                   for k in range(N_STEPS)])

    nav_out = [cur] + panels + nav
    for k, btn in enumerate(nav):
        btn.click(lambda k=k: goto(k), None, nav_out)
    b_prev.click(lambda c: goto(c - 1), [cur], nav_out)
    b_next.click(lambda c: goto(c + 1), [cur], nav_out)

    # ══════════════════════════════════════════ step 1
    def on1(video, name):
        if not video:
            yield "Please choose a video first.", None, DL_HIDDEN, "", ""
            return
        # 命名在点了 Run 之后才校验：空名字要求补，重名直接拒绝，
        # 否则 GVHMR 会静默复用同名目录下的旧结果。
        clean = P.safe_name(name)
        if not (name or "").strip():
            yield ("Please enter a project name above, then press Run again.\n"
                   f"Names already used: {', '.join(P.list_smpl()) or '(none)'}",
                   None, DL_HIDDEN, "", "")
            return
        if clean in P.list_smpl():
            yield (f'The name "{clean}" already exists. Pick a different one.\n'
                   f"Names already used: {', '.join(P.list_smpl())}",
                   None, DL_HIDDEN, "", "")
            return
        job = P.Job("s1")
        for t in drive(job, P.step1, video, name):
            yield t, None, DL_HIDDEN, "", ""
        r = job.result
        yield (job.tail(), r.get("preview"),
               dl(r.get("download"), "Download SMPL-X result"),
               r.get("name", ""), r.get("pt", ""))

    b1.click(on1, [in_video, in_name], [log1, out_smpl, d1, s_name, s_pt])
    b1.click(lambda: gr.update(choices=P.list_smpl()), None, src2)

    # ══════════════════════════════════════════ step 2
    def on2(sel, name, pt):
        chosen = sel or name
        if not chosen:
            yield "Run Step 1 first, or pick an existing result.", None, \
                  DL_HIDDEN, "", ""
            return
        pt_path = pt if (not sel and pt) else P.smpl_pt(chosen)
        if not Path(pt_path).exists():
            yield f"Not found: {pt_path}", None, DL_HIDDEN, "", ""
            return
        job = P.Job("s2")
        for t in drive(job, P.step2, chosen, pt_path):
            yield t, None, DL_HIDDEN, "", ""
        r = job.result
        yield (job.tail(), r.get("replay"),
               dl(r.get("download"), "Download G1 trajectory"),
               r.get("bm", ""), chosen)

    b2.click(on2, [src2, s_name, s_pt], [log2, out_retarget, d2, s_bm, s_name])
    b2.click(lambda: gr.update(choices=P.list_motions()), None, src3)
    r2.click(lambda: gr.update(choices=P.list_smpl()), None, src2)

    # ══════════════════════════════════════════ step 3
    def show_est(h, ck):
        h = max(float(h or 0), 0.0)
        steps = int(h * 3600 * P.THROUGHPUT)
        n = max(1, int(round(steps / (max(float(ck or 1), .5) * 1e6))))
        return (f"**≈ {steps/1e6:,.0f} M env-steps** · {n} checkpoints · "
                f"{steps/500e6*100:.0f}% of a fully converged 500M run")

    hours.change(show_est, [hours, ck_every], est)
    ck_every.change(show_est, [hours, ck_every], est)
    demo.load(show_est, [hours, ck_every], est)

    def on3(sel, bm, name, h, ck):
        motion = P.motion_bm(sel) if sel else bm
        mname = sel or name
        if not motion or not Path(motion).exists():
            yield ("Run Step 2 first, or pick an existing motion.",
                   None, DL_HIDDEN, "", None)
            return
        job = P.Job("s3")
        threading.Thread(target=P.step3_train,
                         args=(motion, mname, float(h), float(ck), job),
                         daemon=True).start()
        while not job.done:
            yield job.tail(), curves(job.result.get("curve")), DL_HIDDEN, "", job
            time.sleep(1.5)
        r = job.result
        yield (job.tail(), curves(r.get("curve")),
               dl(r.get("download"), "Download all checkpoints"),
               r.get("params", ""), job)

    b3.click(on3, [src3, s_bm, s_name, hours, ck_every],
             [log3, plot3, d3, s_params, train_job])
    b3.click(lambda: gr.update(choices=P.list_runs()), None, run4)
    b3stop.click(lambda j: (j.stop() or j.tail()) if j else "Nothing running.",
                 [train_job], log3)
    r3.click(lambda: gr.update(choices=P.list_motions()), None, src3)

    # ══════════════════════════════════════════ step 4
    mode4.change(lambda m: (gr.update(visible=m == "Pre-trained policy"),
                            gr.update(visible=m != "Pre-trained policy"),
                            gr.update(visible=m != "Pre-trained policy")),
                 [mode4], [preset, run4, ck4])
    r4.click(lambda r: (gr.update(choices=P.list_runs()),
                        gr.update(choices=P.list_checkpoints(r) if r else [])),
             [run4], [run4, ck4])
    run4.change(lambda r: gr.update(
        choices=P.list_checkpoints(r),
        value="params_best" if "params_best" in P.list_checkpoints(r) else None),
        [run4], ck4)

    def on4(mode, pre_label, run, ck, bm, name):
        if mode == "Pre-trained policy":
            ps = P.presets()
            if pre_label not in ps:
                yield "No pre-trained motion available.", None, DL_HIDDEN, ""
                return
            p = ps[pre_label]
            if p.get("video") and Path(p["video"]).exists():
                yield ("Loaded the pre-rendered comparison for this policy.",
                       p["video"], dl(p["video"], "Download video"),
                       metrics([("Motion completed", "100", "%"),
                                ("Body position error", "0.036", "m"),
                                ("Training steps", "500", "M"),
                                ("Training time", "479", "min")]))
                return
            args = (p["params"], p["bm"], p["name"])
        else:
            if not run:
                yield "Pick a training run.", None, DL_HIDDEN, ""
                return
            ckpt = str(P.C.TRAIN_OUT / run / (ck or "params_best"))
            mname = run.replace("web_", "").replace("bm_", "")
            motion = bm if bm and Path(bm).exists() else P.motion_bm(mname)
            if not Path(motion).exists():
                yield f"Motion file not found: {motion}", None, DL_HIDDEN, ""
                return
            args = (ckpt, motion, mname)

        job = P.Job("s4")
        for t in drive(job, P.step4_simulate, *args):
            yield t, None, DL_HIDDEN, ""
        r = job.result
        st = r.get("stats", {})
        s = metrics([("Motion completed", f'{st.get("pct", 0):.0f}', "%"),
                     ("Body position error", f'{st.get("err", 0):.4f}', "m"),
                     ("Zero-action baseline", f'{st.get("zero_pct", 0):.0f}', "%")
                     ]) if st else ""
        yield job.tail(), r.get("video"), dl(r.get("download"), "Download video"), s

    b4.click(on4, [mode4, preset, run4, ck4, s_bm, s_name],
             [log4, out_sim, d4, stat4])


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=2).launch(
        server_name="0.0.0.0", server_port=7860,
        css=CSS, theme=gr.themes.Soft(primary_hue="red"),
        # Step 1 previews come straight out of GVHMR's own output tree, which
        # is outside both the working directory and workdir. Gradio refuses to
        # serve a file it cannot attribute to the app, so the step succeeds and
        # then fails on the way back with InvalidPathError.
        allowed_paths=[str(P.C.WORKDIR), str(P.GVHMR / "outputs")])
