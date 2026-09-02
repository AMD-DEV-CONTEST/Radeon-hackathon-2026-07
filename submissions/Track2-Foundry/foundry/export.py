"""Convert the merged student to GGUF and smoke-test the artifact.

Conversion is pure Python (no GPU); the smoke test serves the GGUF with
the same llama-server used for the teacher and requires one valid JSON
triage response — proof the shipped artifact works, not just the
checkpoint.
"""

import json
import subprocess
import sys
from pathlib import Path

from . import task
from .teacher import TeacherClient, start_server, stop_server

SMOKE_PORT = 8124


def export(cfg: dict, run_dir: Path) -> dict:
    overrides_path = run_dir / "export_overrides.json"
    if overrides_path.exists():
        ov = json.loads(overrides_path.read_text(encoding="utf-8"))
        cfg["export"]["quant"] = ov.get("quant", cfg["export"]["quant"])

    merged = run_dir / "merged"
    quant = cfg["export"]["quant"].lower()
    outfile = run_dir / f"student-{quant}.gguf"
    from .llamacpp import resolve_src
    convert = resolve_src(cfg["export"].get("llama_src")) / "convert_hf_to_gguf.py"

    # convert_hf_to_gguf only emits these directly; K-quants (Q4_K_M,
    # Q5_K_M, ...) need the two-step f16 -> llama-quantize path.
    native = {"f32", "f16", "bf16", "q8_0", "tq1_0", "tq2_0"}
    if quant in native:
        cmd = [sys.executable, str(convert), str(merged),
               "--outfile", str(outfile), "--outtype", quant]
        print(f"export: {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"convert_hf_to_gguf failed:\n{result.stderr[-3000:]}")
    else:
        from .bench import _bin, _convert_f16
        f16 = _convert_f16(cfg, run_dir)
        print(f"export: quantizing {f16.name} -> {quant}", flush=True)
        result = subprocess.run(
            [str(_bin(cfg, "llama-quantize")), str(f16), str(outfile),
             quant.upper()], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"llama-quantize failed:\n{result.stderr[-2000:]}")
    size_mb = outfile.stat().st_size / 2**20
    print(f"export: wrote {outfile} ({size_mb:.0f} MB)", flush=True)

    # Smoke test: serve the artifact, run one held-out example through it.
    from .spec import TaskSpec

    spec = TaskSpec.load(run_dir / "spec.json")
    rows = [json.loads(l) for l in open(run_dir / "holdout.jsonl", encoding="utf-8")]
    sample = rows[0][spec.input_field]
    proc = start_server(
        cfg["teacher"]["server_exe"], outfile, SMOKE_PORT,
        n_gpu_layers=99, parallel=1, ctx_per_slot=2048,
    )
    try:
        client = TeacherClient(f"http://127.0.0.1:{SMOKE_PORT}/v1")
        # The student was trained with enable_thinking=False; serving must
        # render the same template or the reply lands in reasoning_content.
        text = client.chat(
            task.student_messages(spec, sample), temperature=0.0, max_tokens=80,
            chat_template_kwargs={"enable_thinking": False},
        )
    finally:
        stop_server(proc)
    parsed, reason = task.parse_response(spec, text)
    if parsed is None:
        raise RuntimeError(
            f"GGUF smoke test failed to produce valid JSON ({reason}): {text!r}"
        )
    print(f"export: smoke test OK — {parsed} for input: {sample[:80]}...", flush=True)
    return {"gguf": str(outfile), "size_mb": round(size_mb), "smoke": parsed}
