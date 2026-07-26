# -*- coding: utf-8 -*-
"""性能基准测试：在各功能上运行标准负载，输出延迟 / 吞吐 / 峰值显存，
并自动生成可写入 docs/BENCHMARKS.md 的 Markdown 结果表。

用法：
    python scripts/benchmark.py --image examples/demo.jpg --iters 3
    python scripts/benchmark.py --image examples/demo.jpg --out docs/BENCHMARKS.md
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from src.device import detect_device, peak_memory_gb, reset_peak_memory, Timer  # noqa: E402
from src.model_manager import ModelManager  # noqa: E402
from src.pipelines import (run_character_split, run_face_restore, run_inpaint,  # noqa: E402
                           run_outpaint, run_poster_batch, run_style, run_upscale)


def _bench(name: str, fn, iters: int, results: list) -> None:
    """对 fn 先预热 1 次再计时 iters 次。"""
    try:
        fn()  # warmup
    except Exception as e:
        results.append({"功能": name, "状态": f"跳过（{type(e).__name__}: {e}）"})
        print(f"[跳过] {name}: {e}")
        return
    times = []
    reset_peak_memory()
    for _ in range(iters):
        with Timer() as t:
            fn()
        times.append(t.elapsed)
    avg = sum(times) / len(times)
    results.append({
        "功能": name, "状态": "OK",
        "平均耗时(s)": round(avg, 3),
        "最快(s)": round(min(times), 3),
        "吞吐(张/分)": round(60.0 / avg, 1) if avg > 0 else 0,
        "峰值显存(GB)": round(peak_memory_gb(), 2),
    })
    print(f"[完成] {name}: avg={avg:.2f}s peak={peak_memory_gb():.2f}GB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="基准测试输入图片")
    parser.add_argument("--iters", type=int, default=3)
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--out", default="", help="写入 Markdown 文件路径（如 docs/BENCHMARKS.md）")
    args = parser.parse_args()

    info = detect_device(settings.device, settings.dtype)
    manager = ModelManager(info, settings)
    print(f"后端：{info.summary()}")

    img = Image.open(args.image).convert("RGB")
    # 构造中心矩形遮罩（模拟典型重绘负载）
    from PIL import ImageDraw
    mask = Image.new("L", img.size, 0)
    w, h = img.size
    ImageDraw.Draw(mask).rectangle([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=255)

    results = []
    _bench("局部重绘 512px/25步（标准）", lambda: run_inpaint(
        manager, img, mask, "a red rose", steps=args.steps, seed=42), args.iters, results)
    _bench("局部重绘 512px/6步（LCM 极速）", lambda: run_inpaint(
        manager, img, mask, "a red rose", steps=args.steps, seed=42, fast=True), args.iters, results)
    _bench("智能扩图 +256px/25步", lambda: run_outpaint(
        manager, img, 0, 256, 0, 0, "extended scenery", steps=args.steps, seed=42), args.iters, results)
    _bench("风格迁移 img2img/25步", lambda: run_style(
        manager, img, "日系动漫", steps=args.steps, seed=42), args.iters, results)
    _bench("超分 x4（轻量档）", lambda: run_upscale(
        manager, img, "fast", 4.0), args.iters, results)
    _bench("超分 x4（高画质档）", lambda: run_upscale(
        manager, img, "hq", 4.0), args.iters, results)
    _bench("人像修复（GFPGAN）", lambda: run_face_restore(
        manager, img, False), args.iters, results)
    _bench("素材拆分（BiRefNet 抠图）", lambda: run_character_split(
        manager, img, False), args.iters, results)
    _bench("海报生成（文生图25步×2张）", lambda: run_poster_batch(
        manager, "fresh product photo, studio lighting", "",
        "方形主图 1:1（1024×1024）", "夏日狂欢节", "全场五折起", "",
        "底部横幅", count=2, steps=args.steps, seed=42), args.iters, results)

    meta = {
        "date": datetime.date.today().isoformat(),
        "backend": info.summary(),
        "input": f"{w}x{h}", "steps": args.steps, "iters": args.iters,
    }
    Path("benchmark_results.json").write_text(
        json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=2))
    print("原始数据已写入 benchmark_results.json")

    # 生成 Markdown 表
    lines = [
        f"> 测试时间：{meta['date']}　后端：{meta['backend']}　输入：{meta['input']}　扩散步数：{args.steps}",
        "",
        "| 功能 | 平均耗时(s) | 最快(s) | 吞吐(张/分) | 峰值显存(GB) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        if r.get("状态") == "OK":
            lines.append(f"| {r['功能']} | {r['平均耗时(s)']} | {r['最快(s)']} | "
                         f"{r['吞吐(张/分)']} | {r['峰值显存(GB)']} |")
        else:
            lines.append(f"| {r['功能']} | {r['状态']} | - | - | - |")
    md = "\n".join(lines)
    print("\n" + md)
    if args.out:
        out_path = Path(args.out)
        old = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        marker = "<!-- BENCHMARK_RESULTS -->"
        if marker in old:
            old = old.split(marker)[0] + marker + "\n\n"
        out_path.write_text(old + md + "\n", encoding="utf-8")
        print(f"\n结果表已写入 {args.out}")


if __name__ == "__main__":
    main()
