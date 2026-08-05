"""Benchmark harness: quantization ladder + speed + served accuracy.

Produces the submission artifacts for the inference-speed rubric line:
for each quantization of the tuned student — file size, llama-bench
prompt-processing and generation tok/s, and accuracy on the frozen
holdout measured THROUGH llama-server (the deployed artifact, not the
HF checkpoint) — plus the teacher's speed on the same silicon.
Writes bench_report.json, bench_report.md, and bench_chart.png.

Speed numbers only count on the device they were measured on: CUDA
runs validate mechanics; Radeon runs produce submission numbers.
"""

import json
import platform
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import task
from .spec import TaskSpec
from .teacher import TeacherClient, start_server, stop_server

BENCH_PORT = 8125
DEFAULT_QUANTS = ["Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0"]


def _device_name() -> str:
    """Name the GPU for the report/chart: nvidia-smi, then rocm-smi."""
    for cmd, parse in (
        (["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
         lambda s: s.strip().splitlines()[0].strip()),
        (["rocminfo"],
         lambda s: next((l.split(":", 1)[1].strip() for l in s.splitlines()
                         if "Marketing Name" in l and "CPU" not in l
                         and "EPYC" not in l), None)),
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=15)
            if out.returncode == 0:
                name = parse(out.stdout)
                if name:
                    return name
        except (OSError, subprocess.TimeoutExpired):
            continue
    return platform.system()


def _bin(cfg: dict, name: str) -> Path:
    """Locate a llama.cpp binary (config path first, then fallbacks)."""
    from .llamacpp import resolve_binary
    return resolve_binary(cfg["teacher"].get("server_exe"), name)


def _size_mb(path: Path) -> int:
    return round(path.stat().st_size / 2**20)


def _convert_f16(cfg: dict, run_dir: Path) -> Path:
    f16 = run_dir / "student-f16.gguf"
    if f16.exists():
        return f16
    from .llamacpp import resolve_src
    convert = resolve_src(cfg["export"].get("llama_src")) / "convert_hf_to_gguf.py"
    cmd = [sys.executable, str(convert), str(run_dir / "merged"),
           "--outfile", str(f16), "--outtype", "f16"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"f16 convert failed:\n{result.stderr[-2000:]}")
    return f16


def _quantize(cfg: dict, f16: Path, quant: str, run_dir: Path) -> Path:
    out = run_dir / f"student-{quant.lower()}.gguf"
    if out.exists():
        return out
    cmd = [str(_bin(cfg, "llama-quantize")), str(f16), str(out), quant]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"llama-quantize {quant} failed:\n{result.stderr[-2000:]}")
    return out


def _llama_bench(cfg: dict, gguf: Path) -> dict:
    """pp512 / tg128 tok/s via llama-bench."""
    cmd = [str(_bin(cfg, "llama-bench")), "-m", str(gguf),
           "-ngl", "99", "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if result.returncode != 0:
        raise RuntimeError(f"llama-bench failed:\n{result.stderr[-2000:]}")
    rows = json.loads(result.stdout)
    out = {}
    for row in rows:
        if row.get("n_prompt", 0) > 0 and row.get("n_gen", 0) == 0:
            out["pp_ts"] = round(row["avg_ts"], 1)
        elif row.get("n_gen", 0) > 0 and row.get("n_prompt", 0) == 0:
            out["tg_ts"] = round(row["avg_ts"], 1)
    if "tg_ts" not in out:
        raise RuntimeError(f"llama-bench output missing tg result: {result.stdout[:500]}")
    return out


def _served_accuracy(cfg: dict, gguf: Path, spec: TaskSpec, rows: list) -> dict:
    """Holdout accuracy through llama-server — the artifact users deploy."""
    proc = start_server(cfg["teacher"]["server_exe"], gguf, BENCH_PORT,
                        n_gpu_layers=99, parallel=4, ctx_per_slot=2048)
    try:
        client = TeacherClient(f"http://127.0.0.1:{BENCH_PORT}/v1")

        def one(row):
            text = client.chat(
                task.student_messages(spec, row[spec.input_field]),
                temperature=0.0, max_tokens=80,
                chat_template_kwargs={"enable_thinking": False},
            )
            parsed, _ = task.parse_response(spec, text)
            return parsed

        with ThreadPoolExecutor(max_workers=4) as pool:
            predictions = list(pool.map(one, rows))
    finally:
        stop_server(proc)
    refs = [{f: r[f] for f in spec.output_fields()} for r in rows]
    return task.score(spec, predictions, refs)


def _chart(report: dict, out_png: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    quants = [q["quant"] for q in report["quants"]]
    exact = [q["accuracy"]["exact_match"] for q in report["quants"]]
    tg = [q["tg_ts"] for q in report["quants"]]
    sizes = [q["size_mb"] for q in report["quants"]]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    bars = ax1.bar(quants, exact, color="#2f6fed")
    ax1.set_ylim(0, 1.0)
    ax1.set_title("Served accuracy by quantization (exact match)")
    for bar, size in zip(bars, sizes):
        ax1.annotate(f"{size} MB", (bar.get_x() + bar.get_width() / 2, 0.02),
                     ha="center", color="white", fontsize=9)
    ax2.plot(quants, tg, marker="o", color="#e0662d", label="student tg tok/s")
    if report.get("teacher", {}).get("tg_ts"):
        ax2.axhline(report["teacher"]["tg_ts"], linestyle="--", color="#777",
                    label=f"teacher ({report['teacher']['tg_ts']} tok/s)")
    ax2.set_title(f"Generation speed — {report['device']}")
    ax2.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)
    plt.close(fig)


def run_bench(cfg: dict, run_dir: Path, quants: list[str] | None = None,
              bench_teacher: bool = True) -> dict:
    quants = quants or DEFAULT_QUANTS
    spec = TaskSpec.load(run_dir / "spec.json")
    rows = [json.loads(l) for l in open(run_dir / "holdout.jsonl", encoding="utf-8")]

    report = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "device": _device_name(),
        "task": spec.name,
        "holdout_n": len(rows),
        "quants": [],
    }

    f16 = _convert_f16(cfg, run_dir)
    print(f"bench: f16 base {_size_mb(f16)} MB", flush=True)

    for quant in quants:
        gguf = _quantize(cfg, f16, quant, run_dir)
        t0 = time.time()
        speed = _llama_bench(cfg, gguf)
        acc = _served_accuracy(cfg, gguf, spec, rows)
        entry = {"quant": quant, "gguf": str(gguf), "size_mb": _size_mb(gguf),
                 **speed, "accuracy": acc,
                 "seconds": round(time.time() - t0, 1)}
        report["quants"].append(entry)
        print(f"bench: {quant}: {entry['size_mb']} MB, "
              f"tg {entry.get('tg_ts')} tok/s, exact {acc['exact_match']:.3f}",
              flush=True)

    if bench_teacher:
        tspeed = _llama_bench(cfg, Path(cfg["teacher"]["gguf"]))
        report["teacher"] = {"gguf": str(cfg["teacher"]["gguf"]),
                             "size_mb": _size_mb(Path(cfg["teacher"]["gguf"])),
                             **tspeed}
        print(f"bench: teacher: {report['teacher']['size_mb']} MB, "
              f"tg {tspeed.get('tg_ts')} tok/s", flush=True)

    (run_dir / "bench_report.json").write_text(json.dumps(report, indent=2))
    lines = [f"# Benchmark — {spec.name} ({report['device']})", "",
             "| Quant | Size (MB) | pp tok/s | tg tok/s | Exact match |",
             "|---|---|---|---|---|"]
    for q in report["quants"]:
        lines.append(f"| {q['quant']} | {q['size_mb']} | {q.get('pp_ts', '-')} "
                     f"| {q.get('tg_ts', '-')} | {q['accuracy']['exact_match']:.3f} |")
    if "teacher" in report:
        lines.append(f"| teacher | {report['teacher']['size_mb']} | "
                     f"{report['teacher'].get('pp_ts', '-')} | "
                     f"{report['teacher'].get('tg_ts', '-')} | (labels) |")
    (run_dir / "bench_report.md").write_text("\n".join(lines), encoding="utf-8")
    _chart(report, run_dir / "bench_chart.png")
    print(f"bench: report + chart written to {run_dir}", flush=True)
    return report
