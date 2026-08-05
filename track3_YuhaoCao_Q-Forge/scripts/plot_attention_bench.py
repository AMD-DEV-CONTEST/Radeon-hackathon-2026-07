"""Render the FA-vs-SDPA attention benchmark as a static SVG and an interactive HTML page.

Reads the JSON emitted by benchmark_attention_fa_vs_sdpa.py. The SVG is embedded in
the markdown report; the HTML adds a crosshair/tooltip layer, a table view and a
theme toggle. Both are generated from the same geometry so they never disagree.
"""

import argparse
import html
import json
import math

# Three slots of the reference categorical palette, plus chrome ink.
# Validated with dataviz/scripts/validate_palette.js: all six checks PASS in both
# modes (worst adjacent CVD dE 24.7 light / 26.8 dark, target >= 8).
THEME = {
    "light": {
        "surface": "#fcfcfb", "page": "#f9f9f7", "primary": "#0b0b0b",
        "secondary": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
        "axis": "#c3c2b7", "s1": "#2a78d6", "s2": "#eb6834", "s3": "#1baf7a",
        "border": "rgba(11,11,11,0.10)",
    },
    "dark": {
        "surface": "#1a1a19", "page": "#0d0d0d", "primary": "#ffffff",
        "secondary": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
        "axis": "#383835", "s1": "#3987e5", "s2": "#e87845", "s3": "#28bd89",
        "border": "rgba(255,255,255,0.10)",
    },
}

SERIES = [
    ("flash_attn", "FA-CK", "s1"),
    ("flash_attn_triton", "FA-Triton", "s2"),
    ("sdpa", "torch SDPA", "s3"),
]
FA_SERIES = SERIES[:2]
PANELS = [("fwd", "Forward"), ("bwd", "Backward")]

# Step-time figure: latency spans two decades (0.66 ms -> 88 ms), so the left
# panel is log-scaled. A constant ratio then reads as a constant vertical gap.
STEP_TICKS = [0.5, 1, 2, 5, 10, 20, 50, 100]
LOG_LO, LOG_HI = 0.5, 100.0
PCT_MAX = 180.0
PCT_TICKS = [0, 40, 80, 120, 160]

# Geometry
W, H = 920, 466
PLOT_Y0, PLOT_H = 108, 264
PLOT_Y1 = PLOT_Y0 + PLOT_H
PANEL_W = 356
PANEL_X = [56, 498]          # left edge of each plot area
END_LABEL_DX = 11
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def esc(s):
    return html.escape(str(s), quote=True)


def chrome_vars(mode):
    """Custom-property declarations for the HTML page chrome."""
    return "\n".join(f"    --{k}: {v};" for k, v in THEME[mode].items())


def build_scales(rows, y_max):
    xs = [r["seqlen"] for r in rows]
    lo, hi = math.log2(min(xs)), math.log2(max(xs))

    def x_of(panel_i, seqlen):
        frac = (math.log2(seqlen) - lo) / (hi - lo)
        return PANEL_X[panel_i] + frac * PANEL_W

    def y_of(val):
        return PLOT_Y1 - (val / y_max) * PLOT_H

    return x_of, y_of


def style_block(for_html):
    """Dark-mode overrides for the SVG.

    Light values are emitted as presentation attributes on the marks themselves, so
    the figure is correct in any renderer -- including ones that ignore CSS (older
    markdown pipelines, rasterizers). CSS then *upgrades* to dark where supported:
    class rules beat presentation attributes, so these win when the media query or
    the theme scope matches. Custom properties are deliberately avoided here; an
    SVG loaded via <img> must not depend on them resolving.
    """
    d = THEME["dark"]
    rules = f"""
  .viz-bg     {{ fill: {d['surface']}; }}
  .viz-grid   {{ stroke: {d['grid']}; }}
  .viz-axis   {{ stroke: {d['axis']}; }}
  .viz-title, .viz-panel, .viz-endlab {{ fill: {d['primary']}; }}
  .viz-sub, .viz-axlab, .viz-legend   {{ fill: {d['secondary']}; }}
  .viz-tick, .viz-foot                {{ fill: {d['muted']}; }}
  .viz-line.viz-s1 {{ stroke: {d['s1']}; }}
  .viz-line.viz-s2 {{ stroke: {d['s2']}; }}
  .viz-line.viz-s3 {{ stroke: {d['s3']}; }}
  .viz-dot.viz-s1  {{ fill: {d['s1']}; stroke: {d['surface']}; }}
  .viz-dot.viz-s2  {{ fill: {d['s2']}; stroke: {d['surface']}; }}
  .viz-dot.viz-s3  {{ fill: {d['s3']}; stroke: {d['surface']}; }}
  .viz-bar.viz-s1  {{ fill: {d['s1']}; }}
  .viz-bar.viz-s2  {{ fill: {d['s2']}; }}"""

    css = f"""  .viz-line {{ fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }}
  .viz-dot  {{ stroke-width: 2; }}
  .viz-grid, .viz-axis {{ stroke-width: 1; }}
  .viz-title  {{ font-weight: 600; font-size: 15px; }}
  .viz-sub    {{ font-size: 12px; }}
  .viz-panel  {{ font-weight: 600; font-size: 12.5px; }}
  .viz-tick   {{ font-size: 10.5px; font-variant-numeric: tabular-nums; }}
  .viz-axlab  {{ font-size: 11px; }}
  .viz-endlab {{ font-size: 11px; font-weight: 600; }}
  .viz-legend {{ font-size: 12px; }}
  .viz-foot   {{ font-size: 10.5px; }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) {{{rules}
    }}
  }}"""
    if for_html:
        css += f"""
  :root[data-theme="dark"] {{{rules}
  }}"""
    return css


def svg(rows, meta, for_html=False):
    y_max = 65.0
    ticks = [0, 10, 20, 30, 40, 50, 60]
    x_of, y_of = build_scales(rows, y_max)
    seqlens = [r["seqlen"] for r in rows]
    L = THEME["light"]
    o = []

    o.append(
        f'<svg class="viz-root" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" font-family=\'{FONT}\' role="img" '
        f'aria-label="Attention throughput, FlashAttention CK and Triton versus torch SDPA, '
        f'forward and backward, sequence length 256 to 4096">'
    )
    o.append(f"<style>\n{style_block(for_html)}\n</style>")
    o.append(f'<rect class="viz-bg" width="{W}" height="{H}" fill="{L["surface"]}"/>')

    o.append(
        f'<text class="viz-title" x="24" y="30" fill="{L["primary"]}">CK wins the forward pass; '
        f'SDPA keeps the strongest backward throughput</text>'
    )
    o.append(
        f'<text class="viz-sub" x="24" y="50" fill="{L["secondary"]}">AMD gfx1100 · '
        f'fp16, causal · batch {meta["batch"]} × {meta["heads"]} heads × '
        f'{meta["head_dim"]} head dim · higher is better</text>'
    )

    # Legend — always present for two or more series; line keys mirror the marks.
    lx = 24
    for key, label, slot in SERIES:
        o.append(
            f'<line class="viz-line viz-{slot}" x1="{lx}" y1="72" x2="{lx + 16}" y2="72" '
            f'stroke="{L[slot]}"/>'
            f'<circle class="viz-dot viz-{slot}" cx="{lx + 8}" cy="72" r="4" '
            f'fill="{L[slot]}" stroke="{L["surface"]}"/>'
            f'<text class="viz-legend" x="{lx + 24}" y="76" fill="{L["secondary"]}">{esc(label)}</text>'
        )
        lx += 24 + len(label) * 6.6 + 26

    for pi, (pass_name, panel_title) in enumerate(PANELS):
        px0, px1 = PANEL_X[pi], PANEL_X[pi] + PANEL_W
        o.append(
            f'<text class="viz-panel" x="{px0}" y="{PLOT_Y0 - 14}" '
            f'fill="{L["primary"]}">{panel_title}</text>'
        )

        for t in ticks:
            y = y_of(t)
            cls, col = ("viz-axis", L["axis"]) if t == 0 else ("viz-grid", L["grid"])
            o.append(
                f'<line class="{cls}" x1="{px0}" y1="{y:.1f}" x2="{px1}" y2="{y:.1f}" stroke="{col}"/>'
            )
            o.append(
                f'<text class="viz-tick" x="{px0 - 9}" y="{y + 3.5:.1f}" text-anchor="end" '
                f'fill="{L["muted"]}">{t}</text>'
            )

        for s in seqlens:
            x = x_of(pi, s)
            o.append(
                f'<text class="viz-tick" x="{x:.1f}" y="{PLOT_Y1 + 18}" text-anchor="middle" '
                f'fill="{L["muted"]}">{s}</text>'
            )
        o.append(
            f'<text class="viz-axlab" x="{(px0 + px1) / 2:.1f}" y="{PLOT_Y1 + 40}" '
            f'text-anchor="middle" fill="{L["secondary"]}">Sequence length</text>'
        )
        if pi == 0:
            o.append(
                f'<text class="viz-axlab" x="{-((PLOT_Y0 + PLOT_Y1) / 2):.1f}" y="18" '
                f'transform="rotate(-90)" text-anchor="middle" '
                f'fill="{L["secondary"]}">Throughput (TFLOP/s)</text>'
            )

        for key, label, slot in SERIES:
            pts = [(x_of(pi, r["seqlen"]), y_of(r[f"{key}_{pass_name}_tflops"])) for r in rows]
            d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
            o.append(f'<path class="viz-line viz-{slot}" d="{d}" stroke="{L[slot]}"/>')
            for x, y in pts:
                # 2px surface ring keeps markers legible where they cross a line.
                o.append(
                    f'<circle class="viz-dot viz-{slot}" cx="{x:.1f}" cy="{y:.1f}" r="4" '
                    f'fill="{L[slot]}" stroke="{L["surface"]}"/>'
                )
            # Direct-label the endpoint only; the axis and tooltip carry the rest.
            ex, ey = pts[-1]
            val = rows[-1][f"{key}_{pass_name}_tflops"]
            label_dy = 0
            if pass_name == "bwd":
                label_dy = {"s1": 11, "s2": 0, "s3": -10}[slot]
            o.append(
                f'<text class="viz-endlab" x="{ex + END_LABEL_DX:.1f}" y="{ey + 4 + label_dy:.1f}" '
                f'fill="{L["primary"]}">{val:.1f}</text>'
            )

    o.append(
        f'<text class="viz-foot" x="24" y="{H - 14}" fill="{L["muted"]}">Median of '
        f'{meta["iters"]} timed iterations after {meta["warmup"]} warmups. FLOPs counted as '
        f'4·B·H·S²·D (×0.5 causal), backward ×2.5. Each implementation gets its native layout.</text>'
    )
    o.append("</svg>")
    return "\n".join(o)


def y_log(v):
    f = (math.log10(v) - math.log10(LOG_LO)) / (math.log10(LOG_HI) - math.log10(LOG_LO))
    return PLOT_Y1 - f * PLOT_H


def y_pct(v):
    return PLOT_Y1 - (v / PCT_MAX) * PLOT_H


def bar_geom(i, n):
    """Centre and width of the i-th column band. Bars are capped well below the
    band width so the leftover is air, never a filled slot."""
    band = PANEL_W / n
    return PANEL_X[1] + band * (i + 0.5), min(22.0, (band - 14) / 2)


def rounded_col(cx, w, y_top, y_base, r=4.0):
    """Column path: 4px rounded cap, square at the baseline."""
    x0, x1 = cx - w / 2, cx + w / 2
    r = min(r, w / 2, max(0.0, y_base - y_top))
    return (
        f"M{x0:.1f},{y_base:.1f} L{x0:.1f},{y_top + r:.1f} "
        f"Q{x0:.1f},{y_top:.1f} {x0 + r:.1f},{y_top:.1f} "
        f"L{x1 - r:.1f},{y_top:.1f} Q{x1:.1f},{y_top:.1f} {x1:.1f},{y_top + r:.1f} "
        f"L{x1:.1f},{y_base:.1f} Z"
    )


def step_penalties(rows, key):
    """Extra wall-clock backend cost per training step versus SDPA, in percent."""
    return [
        (r[f"{key}_step_ms"] / r["sdpa_step_ms"] - 1.0) * 100.0 for r in rows
    ]


def svg_step(rows, meta, for_html=False):
    """Figure 2: full training step cost and both FA backends' penalty against SDPA."""
    x_of, _ = build_scales(rows, 1.0)
    seqlens = [r["seqlen"] for r in rows]
    penalties = {key: step_penalties(rows, key) for key, _, _ in FA_SERIES}
    L = THEME["light"]
    o = []

    o.append(
        f'<svg class="viz-root" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" font-family=\'{FONT}\' role="img" '
        f'aria-label="Full training step time and FlashAttention CK and Triton penalty versus SDPA, '
        f'sequence length 256 to 4096">'
    )
    o.append(f"<style>\n{style_block(for_html)}\n</style>")
    o.append(f'<rect class="viz-bg" width="{W}" height="{H}" fill="{L["surface"]}"/>')
    o.append(
        f'<text class="viz-title" x="24" y="30" fill="{L["primary"]}">SDPA wins every full training '
        f'step; Triton carries the largest short-sequence penalty</text>'
    )
    o.append(
        f'<text class="viz-sub" x="24" y="50" fill="{L["secondary"]}">Forward + backward, '
        f'autograd graph rebuilt each iteration · AMD gfx1100 · fp16, causal · '
        f'batch {meta["batch"]} × {meta["heads"]} heads × {meta["head_dim"]} head dim</text>'
    )

    # ---- Panel A: step latency, log scale, three series ----
    lx = 24
    for key, label, slot in SERIES:
        o.append(
            f'<line class="viz-line viz-{slot}" x1="{lx}" y1="72" x2="{lx + 16}" y2="72" '
            f'stroke="{L[slot]}"/>'
            f'<circle class="viz-dot viz-{slot}" cx="{lx + 8}" cy="72" r="4" '
            f'fill="{L[slot]}" stroke="{L["surface"]}"/>'
            f'<text class="viz-legend" x="{lx + 24}" y="76" fill="{L["secondary"]}">{esc(label)}</text>'
        )
        lx += 24 + len(label) * 6.6 + 26

    px0, px1 = PANEL_X[0], PANEL_X[0] + PANEL_W
    o.append(
        f'<text class="viz-panel" x="{px0}" y="{PLOT_Y0 - 14}" fill="{L["primary"]}">'
        f'Step time · log scale</text>'
    )
    for t in STEP_TICKS:
        y = y_log(t)
        cls, col = ("viz-axis", L["axis"]) if t == LOG_LO else ("viz-grid", L["grid"])
        o.append(f'<line class="{cls}" x1="{px0}" y1="{y:.1f}" x2="{px1}" y2="{y:.1f}" stroke="{col}"/>')
        lab = f"{t:g}"
        o.append(
            f'<text class="viz-tick" x="{px0 - 9}" y="{y + 3.5:.1f}" text-anchor="end" '
            f'fill="{L["muted"]}">{lab}</text>'
        )
    o.append(
        f'<text class="viz-axlab" x="{-((PLOT_Y0 + PLOT_Y1) / 2):.1f}" y="18" '
        f'transform="rotate(-90)" text-anchor="middle" '
        f'fill="{L["secondary"]}">Time per step (ms)</text>'
    )
    for s in seqlens:
        o.append(
            f'<text class="viz-tick" x="{x_of(0, s):.1f}" y="{PLOT_Y1 + 18}" text-anchor="middle" '
            f'fill="{L["muted"]}">{s}</text>'
        )
    o.append(
        f'<text class="viz-axlab" x="{(px0 + px1) / 2:.1f}" y="{PLOT_Y1 + 40}" text-anchor="middle" '
        f'fill="{L["secondary"]}">Sequence length</text>'
    )
    for key, label, slot in SERIES:
        pts = [(x_of(0, r["seqlen"]), y_log(r[f"{key}_step_ms"])) for r in rows]
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
        o.append(f'<path class="viz-line viz-{slot}" d="{d}" stroke="{L[slot]}"/>')
        for x, y in pts:
            o.append(
                f'<circle class="viz-dot viz-{slot}" cx="{x:.1f}" cy="{y:.1f}" r="4" '
                f'fill="{L[slot]}" stroke="{L["surface"]}"/>'
            )
        ex, ey = pts[-1]
        short_label = {
            "flash_attn": "CK",
            "flash_attn_triton": "Triton",
            "sdpa": "SDPA",
        }[key]
        label_dy = {"s1": 0, "s2": -12, "s3": 24}[slot]
        o.append(
            f'<text class="viz-endlab" x="{ex + END_LABEL_DX:.1f}" y="{ey + 4 + label_dy:.1f}" '
            f'fill="{L["primary"]}">{short_label} {rows[-1][f"{key}_step_ms"]:.0f} ms</text>'
        )

    # ---- Panel B: grouped CK/Triton penalties, columns from a true zero ----
    bx0, bx1 = PANEL_X[1], PANEL_X[1] + PANEL_W
    o.append(
        f'<text class="viz-panel" x="{bx0}" y="{PLOT_Y0 - 14}" fill="{L["primary"]}">'
        f'Penalty vs SDPA</text>'
    )
    for t in PCT_TICKS:
        y = y_pct(t)
        cls, col = ("viz-axis", L["axis"]) if t == 0 else ("viz-grid", L["grid"])
        o.append(f'<line class="{cls}" x1="{bx0}" y1="{y:.1f}" x2="{bx1}" y2="{y:.1f}" stroke="{col}"/>')
        o.append(
            f'<text class="viz-tick" x="{bx0 - 9}" y="{y + 3.5:.1f}" text-anchor="end" '
            f'fill="{L["muted"]}">{f"+{t}%" if t else "0"}</text>'
        )
    o.append(
        f'<text class="viz-axlab" x="{(bx0 + bx1) / 2:.1f}" y="{PLOT_Y1 + 40}" text-anchor="middle" '
        f'fill="{L["secondary"]}">Sequence length</text>'
    )
    base = y_pct(0)
    for i, s in enumerate(seqlens):
        cx, w = bar_geom(i, len(seqlens))
        for j, (key, _, slot) in enumerate(FA_SERIES):
            pct = penalties[key][i]
            bar_cx = cx + (-0.58 if j == 0 else 0.58) * w
            o.append(
                f'<path class="viz-bar viz-{slot}" data-i="{i}" '
                f'd="{rounded_col(bar_cx, w, y_pct(pct), base)}" fill="{L[slot]}"/>'
            )
            o.append(
                f'<text class="viz-tick" x="{bar_cx:.1f}" y="{y_pct(pct) - 6:.1f}" '
                f'text-anchor="middle" fill="{L["primary"]}">{pct:.0f}%</text>'
            )
        o.append(
            f'<text class="viz-tick" x="{cx:.1f}" y="{PLOT_Y1 + 18}" text-anchor="middle" '
            f'fill="{L["muted"]}">{s}</text>'
        )

    o.append(
        f'<text class="viz-foot" x="24" y="{H - 14}" fill="{L["muted"]}">Median of '
        f'{meta["iters"]} timed iterations after {meta["warmup"]} warmups. Step = one forward '
        f'plus one backward, measured independently of the isolated fwd/bwd numbers.</text>'
    )
    o.append("</svg>")
    return "\n".join(o)
def table_html(all_rows):
    head = (
        "<tr><th>dtype</th><th>causal</th><th>seq len</th>"
        "<th>CK fwd<br>TF/s</th><th>Triton fwd<br>TF/s</th><th>SDPA fwd<br>TF/s</th>"
        "<th>CK bwd<br>TF/s</th><th>Triton bwd<br>TF/s</th><th>SDPA bwd<br>TF/s</th>"
        "<th>CK step<br>ms</th><th>Triton step<br>ms</th><th>SDPA step<br>ms</th></tr>"
    )
    body = []
    for r in all_rows:
        body.append(
            "<tr>"
            f"<td>{r['dtype']}</td><td>{'yes' if r['causal'] else 'no'}</td><td>{r['seqlen']}</td>"
            f"<td>{r['flash_attn_fwd_tflops']:.1f}</td>"
            f"<td>{r['flash_attn_triton_fwd_tflops']:.1f}</td><td>{r['sdpa_fwd_tflops']:.1f}</td>"
            f"<td>{r['flash_attn_bwd_tflops']:.1f}</td>"
            f"<td>{r['flash_attn_triton_bwd_tflops']:.1f}</td><td>{r['sdpa_bwd_tflops']:.1f}</td>"
            f"<td>{r['flash_attn_step_ms']:.2f}</td>"
            f"<td>{r['flash_attn_triton_step_ms']:.2f}</td><td>{r['sdpa_step_ms']:.2f}</td>"
            "</tr>"
        )
    return f"<table><thead>{head}</thead><tbody>{''.join(body)}</tbody></table>"


def geometry(rows):
    """Hover geometry for both figures. Line panels get a crosshair; bar panels
    make the mark itself the hit target, per the interaction spec."""
    x_of, _ = build_scales(rows, 1.0)
    seqlens = [r["seqlen"] for r in rows]
    figs = []

    figs.append({
        "id": "fig-throughput",
        "panels": [
            {
                "kind": "line", "title": title,
                "xs": [x_of(i, s) for s in seqlens],
                "series": [
                    {
                        "label": label, "slot": slot,
                        "text": [
                            f"{r[f'{key}_{p}_tflops']:.1f} TFLOP/s · {r[f'{key}_{p}_ms']:.2f} ms"
                            for r in rows
                        ],
                    }
                    for key, label, slot in SERIES
                ],
            }
            for i, (p, title) in enumerate(PANELS)
        ],
    })

    penalties = {key: step_penalties(rows, key) for key, _, _ in FA_SERIES}
    figs.append({
        "id": "fig-step",
        "panels": [
            {
                "kind": "line", "title": "Step time",
                "xs": [x_of(0, s) for s in seqlens],
                "series": [
                    {
                        "label": label, "slot": slot,
                        "text": [f"{r[f'{key}_step_ms']:.2f} ms" for r in rows],
                    }
                    for key, label, slot in SERIES
                ],
            },
            {
                "kind": "bar", "title": "Extra step time vs SDPA",
                "xs": [bar_geom(i, len(seqlens))[0] for i in range(len(seqlens))],
                "bw": bar_geom(0, len(seqlens))[1],
                "series": [
                    {
                        "label": label, "slot": slot,
                        "text": [f"+{p:.1f}%" for p in penalties[key]],
                    }
                    for key, label, slot in FA_SERIES
                ],
            },
        ],
    })
    return {
        "figs": figs, "y0": PLOT_Y0, "y1": PLOT_Y1, "w": W, "h": H,
        "seqlens": seqlens,
    }


def page(rows, all_rows, meta):
    return f"""<!DOCTYPE html>
<meta charset="utf-8">
<title>Attention benchmark — FlashAttention-2 vs SDPA on gfx1100</title>
<style>
  /* Page chrome (buttons, tooltip, table) is themed with custom properties.
     The SVGs use literal colors + class overrides so they stay portable when
     saved out on their own. */
  .viz-root {{
    color-scheme: light;
{chrome_vars('light')}
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{
      color-scheme: dark;
{chrome_vars('dark')}
    }}
  }}
  :root[data-theme="dark"] .viz-root {{
    color-scheme: dark;
{chrome_vars('dark')}
  }}
  html {{ background: {THEME['light']['page']}; }}
  @media (prefers-color-scheme: dark) {{
    html:where(:not([data-theme="light"])) {{ background: {THEME['dark']['page']}; }}
  }}
  html[data-theme="dark"] {{ background: {THEME['dark']['page']}; }}
  body {{ font-family: {FONT}; margin: 0; padding: 28px; }}
  .wrap {{ max-width: 968px; margin: 0 auto; }}
  .controls {{ display: flex; gap: 8px; margin-bottom: 14px; }}
  button {{ font: inherit; font-size: 12px; padding: 6px 12px; border-radius: 7px;
           background: var(--surface); color: var(--primary);
           border: 1px solid var(--border); cursor: pointer; }}
  button[aria-pressed="true"] {{ font-weight: 600; }}
  .card {{ position: relative; background: var(--surface); margin-bottom: 18px;
          border: 1px solid var(--border); border-radius: 12px; }}
  svg {{ display: block; width: 100%; height: auto; border-radius: 12px; }}
  .hit {{ fill: transparent; }}
  .cross {{ stroke: var(--axis); stroke-width: 1; visibility: hidden; }}
  .viz-bar {{ transition: opacity .1s; }}
  .card.dim .viz-bar {{ opacity: .5; }}
  .card.dim .viz-bar.on {{ opacity: 1; }}
  .tip {{ position: absolute; pointer-events: none; opacity: 0; transition: opacity .1s;
         background: var(--surface); border: 1px solid var(--border); border-radius: 9px;
         padding: 8px 10px; font-size: 12px; color: var(--secondary);
         box-shadow: 0 3px 14px rgba(0,0,0,.13); white-space: nowrap; z-index: 5; }}
  .tip b {{ display: block; color: var(--primary); font-size: 11px; font-weight: 600;
           margin-bottom: 5px; }}
  .tip .row {{ display: flex; align-items: center; gap: 7px; margin-top: 3px; }}
  .tip .key {{ width: 14px; height: 2px; border-radius: 1px; flex: none; }}
  .tip .val {{ color: var(--primary); font-weight: 600;
              font-variant-numeric: tabular-nums; margin-left: auto; padding-left: 12px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 12px;
          color: var(--secondary); font-variant-numeric: tabular-nums; }}
  th, td {{ text-align: right; padding: 6px 9px; border-bottom: 1px solid var(--grid); }}
  th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
  th {{ color: var(--primary); font-weight: 600; font-size: 11px; }}
  #tablewrap[hidden] {{ display: none; }}
</style>
<body>
<div class="wrap viz-root">
  <div class="controls">
    <button id="theme" aria-pressed="false">Toggle dark mode</button>
    <button id="tabletoggle" aria-pressed="false">Show table view</button>
  </div>
  <div class="card" id="fig-throughput">
    {svg(rows, meta, for_html=True)}
    <div class="tip"></div>
  </div>
  <div class="card" id="fig-step">
    {svg_step(rows, meta, for_html=True)}
    <div class="tip"></div>
  </div>
  <div id="tablewrap" hidden>{table_html(all_rows)}</div>
</div>
<script>
const G = {json.dumps(geometry(rows))};
const ns = 'http://www.w3.org/2000/svg';
const cssVar = (n) =>
  getComputedStyle(document.querySelector('.viz-root')).getPropertyValue('--' + n);

G.figs.forEach((fig) => {{
  const card = document.getElementById(fig.id);
  const svgEl = card.querySelector('svg');
  const tip = card.querySelector('.tip');
  const bars = [...svgEl.querySelectorAll('.viz-bar')];

  fig.panels.forEach((p) => {{
    const isBar = p.kind === 'bar';
    let cross = null;
    if (!isBar) {{                       // crosshair finds the X on line panels only
      cross = document.createElementNS(ns, 'line');
      cross.setAttribute('class', 'cross');
      cross.setAttribute('y1', G.y0); cross.setAttribute('y2', G.y1);
      svgEl.appendChild(cross);
    }}
    const lo = Math.min(...p.xs), hi = Math.max(...p.xs);
    const hit = document.createElementNS(ns, 'rect');
    hit.setAttribute('class', 'hit');
    hit.setAttribute('x', lo - 26); hit.setAttribute('y', G.y0 - 18);
    hit.setAttribute('width', hi - lo + 52); hit.setAttribute('height', G.y1 - G.y0 + 36);
    hit.setAttribute('tabindex', '0');
    svgEl.appendChild(hit);

    let idx = 0;
    const show = (i) => {{
      idx = i;
      const scale = svgEl.getBoundingClientRect().width / G.w;
      if (cross) {{
        cross.setAttribute('x1', p.xs[i]); cross.setAttribute('x2', p.xs[i]);
        cross.style.visibility = 'visible';
      }}
      if (isBar) {{                      // the hovered mark lifts instead
        card.classList.add('dim');
        bars.forEach((b) => b.classList.toggle('on', Number(b.dataset.i) === i));
      }}
      tip.textContent = '';
      const head = document.createElement('b');
      head.textContent = `Sequence length ${{G.seqlens[i]}} · ${{p.title}}`;
      tip.appendChild(head);
      for (const s of p.series) {{
        const row = document.createElement('div'); row.className = 'row';
        const key = document.createElement('span'); key.className = 'key';
        key.style.background = cssVar(s.slot);
        const name = document.createElement('span');
        name.textContent = s.label;                  // untrusted label -> textContent
        const val = document.createElement('span'); val.className = 'val';
        val.textContent = s.text[i];
        row.append(key, name, val); tip.appendChild(row);
      }}
      tip.style.opacity = '1';
      let left = p.xs[i] * scale + 16;
      if (left + tip.offsetWidth > card.clientWidth - 6) left = p.xs[i] * scale - tip.offsetWidth - 16;
      tip.style.left = Math.max(6, left) + 'px';
      tip.style.top = (G.y0 * scale + 8) + 'px';
    }};
    const hide = () => {{
      if (cross) cross.style.visibility = 'hidden';
      card.classList.remove('dim');
      bars.forEach((b) => b.classList.remove('on'));
      tip.style.opacity = '0';
    }};

    hit.addEventListener('pointermove', (e) => {{
      const r = svgEl.getBoundingClientRect();
      const x = (e.clientX - r.left) / (r.width / G.w);
      let best = 0;
      p.xs.forEach((xx, i) => {{ if (Math.abs(xx - x) < Math.abs(p.xs[best] - x)) best = i; }});
      show(best);
    }});
    hit.addEventListener('pointerleave', hide);
    hit.addEventListener('focus', () => show(idx));  // keyboard parity with hover
    hit.addEventListener('blur', hide);
    hit.addEventListener('keydown', (e) => {{
      if (e.key === 'ArrowRight') {{ show(Math.min(idx + 1, p.xs.length - 1)); e.preventDefault(); }}
      if (e.key === 'ArrowLeft')  {{ show(Math.max(idx - 1, 0)); e.preventDefault(); }}
    }});
  }});
}});

const themeBtn = document.getElementById('theme');
themeBtn.addEventListener('click', () => {{
  const dark = document.documentElement.getAttribute('data-theme') === 'dark';
  document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
  themeBtn.setAttribute('aria-pressed', String(!dark));
}});
const tblBtn = document.getElementById('tabletoggle');
const tblWrap = document.getElementById('tablewrap');
tblBtn.addEventListener('click', () => {{
  tblWrap.hidden = !tblWrap.hidden;
  tblBtn.setAttribute('aria-pressed', String(!tblWrap.hidden));
  tblBtn.textContent = tblWrap.hidden ? 'Show table view' : 'Hide table view';
}});
</script>
</body>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="reports/attention_bench_gfx1100.json")
    ap.add_argument("--svg-out", default="reports/attention_bench_gfx1100.svg")
    ap.add_argument("--step-svg-out", default="reports/attention_step_gfx1100.svg")
    ap.add_argument("--html-out", default="reports/attention_bench_gfx1100.html")
    args = ap.parse_args()

    blob = json.load(open(args.data))
    meta, all_rows = blob["meta"], blob["rows"]
    # The figures show the training-relevant slice; the table carries everything.
    rows = sorted(
        (r for r in all_rows if r["dtype"] == "fp16" and r["causal"]),
        key=lambda r: r["seqlen"],
    )

    with open(args.svg_out, "w") as fh:
        fh.write(svg(rows, meta))
    with open(args.step_svg_out, "w") as fh:
        fh.write(svg_step(rows, meta))
    with open(args.html_out, "w") as fh:
        fh.write(page(rows, all_rows, meta))
    print(f"wrote {args.svg_out}\nwrote {args.step_svg_out}\nwrote {args.html_out}")


if __name__ == "__main__":
    main()
