#!/usr/bin/env python3
"""Build the AMD attention/rollout evidence slide as an editable SVG."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


COLORS = {"CK FA": "#ef5b67", "Triton FA": "#f2b45f", "SDPA": "#57b8ff"}


def esc(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def line_chart(x, series, x0, y0, w, h, ymax, title, unit, *, log_y=False):
    out = [f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="22" class="panel"/>',
           f'<text x="{x0+28}" y="{y0+45}" class="panel-title">{esc(title)}</text>',
           f'<text x="{x0+w-25}" y="{y0+70}" text-anchor="end" class="unit">{esc(unit)}</text>']
    px0, py0, pw, ph = x0 + 66, y0 + 88, w - 94, h - 147
    for i in range(4):
        value = ymax * i / 3
        if log_y:
            value = 10 ** (math.log10(ymax) * i / 3)
            frac = math.log10(value) / math.log10(ymax)
        else:
            frac = i / 3
        yy = py0 + ph * (1 - frac)
        label = f"{value:.0f}" if value >= 10 else f"{value:.1f}"
        out += [f'<line x1="{px0}" y1="{yy:.1f}" x2="{px0+pw}" y2="{yy:.1f}" class="grid"/>',
                f'<text x="{px0-12}" y="{yy+6:.1f}" text-anchor="end" class="tick">{label}</text>']
    for index, value in enumerate(x):
        xx = px0 + pw * index / (len(x)-1)
        out.append(f'<text x="{xx:.1f}" y="{py0+ph+28}" text-anchor="middle" class="tick">{value}</text>')
    for name, values in series.items():
        points = []
        for index, value in enumerate(values):
            xx = px0 + pw * index / (len(x)-1)
            frac = math.log10(max(value, 1.0)) / math.log10(ymax) if log_y else value / ymax
            yy = py0 + ph * (1 - frac)
            points.append((xx, yy))
        encoded = " ".join(f"{xx:.1f},{yy:.1f}" for xx, yy in points)
        color = COLORS[name]
        out.append(f'<polyline points="{encoded}" fill="none" stroke="{color}" stroke-width="4" stroke-linejoin="round"/>')
        out.extend(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="5" fill="{color}"/>' for xx, yy in points)
    out.append(f'<text x="{x0+w/2}" y="{y0+h-18}" text-anchor="middle" class="axis">sequence length</text>')
    return out


def policy_latency_panel(x0, y0, w, h, latency):
    out = [f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="22" class="panel rollout"/>',
           f'<text x="{x0+28}" y="{y0+45}" class="panel-title">Policy inference latency</text>']
    if not latency:
        out.append(f'<text x="{x0+w/2}" y="{y0+h/2}" text-anchor="middle" class="muted">benchmark pending</text>')
        return out
    medians = {
        key: latency["summary"][key]["median_ms_per_replan"]
        for key in ("sdpa", "fa_ck")
    }
    maximum = max(medians.values()) * 1.12
    left, usable = x0 + 92, w - 190
    for index, (key, label, color) in enumerate((("sdpa", "SDPA", COLORS["SDPA"]), ("fa_ck", "FA-CK", COLORS["CK FA"]))):
        value = medians[key]
        by = y0 + 67 + index * 38
        bw = usable * value / maximum
        out += [f'<text x="{left-12}" y="{by+20}" text-anchor="end" class="tick">{label}</text>',
                f'<rect x="{left}" y="{by}" width="{bw:.1f}" height="25" rx="7" fill="{color}" opacity=".92"/>',
                f'<text x="{left+bw+8:.1f}" y="{by+20}" class="bar-value">{value:.1f}ms</text>']
    ratio = medians["fa_ck"] / medians["sdpa"]
    reduction = (1 - ratio) * 100
    verdict = f"FA-CK {reduction:.2f}% lower" if reduction >= 0 else f"FA-CK {-reduction:.2f}% higher"
    out += [f'<text x="{x0+28}" y="{y0+h-17}" class="foot">{esc(verdict)} · fixed input/noise · synchronized · n=20</text>']
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attention", type=Path, required=True)
    ap.add_argument("--policy-latency", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    payload = json.loads(args.attention.read_text())
    rows = [row for row in payload["rows"] if row["dtype"] == "fp16" and row["causal"] is True]
    x = [row["seqlen"] for row in rows]
    fwd = {"CK FA": [r["flash_attn_fwd_tflops"] for r in rows], "Triton FA": [r["flash_attn_triton_fwd_tflops"] for r in rows], "SDPA": [r["sdpa_fwd_tflops"] for r in rows]}
    bwd = {"CK FA": [r["flash_attn_bwd_tflops"] for r in rows], "Triton FA": [r["flash_attn_triton_bwd_tflops"] for r in rows], "SDPA": [r["sdpa_bwd_tflops"] for r in rows]}
    step = {"CK FA": [r["flash_attn_step_ms"] for r in rows], "Triton FA": [r["flash_attn_triton_step_ms"] for r in rows], "SDPA": [r["sdpa_step_ms"] for r in rows]}
    latency = json.loads(args.policy_latency.read_text()) if args.policy_latency and args.policy_latency.exists() else None
    body = []
    body += line_chart(x, fwd, 70, 260, 560, 610, 65, "Forward throughput", "TFLOP/s · higher is better")
    body += line_chart(x, bwd, 650, 260, 560, 610, 18, "Backward throughput", "TFLOP/s · higher is better")
    body += line_chart(x, step, 1230, 260, 620, 610, 100, "FWD + BWD step", "milliseconds · log scale", log_y=True)
    body += policy_latency_panel(1400, 54, 450, 184, latency)
    legend = []
    for i, name in enumerate(("CK FA", "Triton FA", "SDPA")):
        lx = 76 + i * 190
        legend += [f'<line x1="{lx}" y1="930" x2="{lx+35}" y2="930" stroke="{COLORS[name]}" stroke-width="6"/>', f'<text x="{lx+47}" y="938" class="legend">{name}</text>']
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
<style>.panel{{fill:#151e32;stroke:#31405f;stroke-width:2}}.rollout{{fill:#192741}}.panel-title{{fill:#fff;font:700 27px Inter,Arial,sans-serif}}.unit{{fill:#91a5c5;font:18px Inter,Arial,sans-serif}}.grid{{stroke:#34415c;stroke-width:1}}.tick{{fill:#91a5c5;font:16px Inter,Arial,sans-serif}}.axis,.foot{{fill:#7f93b3;font:16px Inter,Arial,sans-serif}}.legend{{fill:#dce5f3;font:21px Inter,Arial,sans-serif}}.bar-value{{fill:#fff;font:700 21px Inter,Arial,sans-serif}}.verdict{{fill:#fff;font:700 20px Inter,Arial,sans-serif}}.muted{{fill:#91a5c5;font:22px Inter,Arial,sans-serif}}</style>
<rect width="1920" height="1080" fill="#09111f"/>
<text x="70" y="92" fill="#fff" font-family="Inter,Arial,sans-serif" font-size="49" font-weight="700">Built and evaluated on AMD Radeon</text>
<text x="70" y="137" fill="#9fb0cc" font-family="Inter,Arial,sans-serif" font-size="23">gfx1100 · 96 CUs · 48 GiB VRAM · PyTorch 2.8.0 + ROCm 6.4 · causal FP16 attention</text>
<text x="70" y="196" fill="#64d9ac" font-family="Inter,Arial,sans-serif" font-size="24" font-weight="700">Kernel microbenchmark</text>
<text x="420" y="196" fill="#9fb0cc" font-family="Inter,Arial,sans-serif" font-size="20">B=8 · H=16 · D=64 · warmup 5 · timed iterations 20</text>
{''.join(body)}{''.join(legend)}
<text x="70" y="1003" fill="#fff" font-family="Inter,Arial,sans-serif" font-size="22" font-weight="700">Measured result:</text>
<text x="300" y="1003" fill="#b7c5d9" font-family="Inter,Arial,sans-serif" font-size="21">CK dominates forward throughput; SDPA wins backward and the complete training step.</text>
<text x="1850" y="1038" text-anchor="end" fill="#647897" font-family="Inter,Arial,sans-serif" font-size="15">Q-Forge · reproducible artifacts in reports/</text>
</svg>'''
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    main()
