"""Evaluate students against the teacher's held-out labels, spec-driven.

Runs the identical harness over the base (untrained) student and the
tuned one, so every eval report carries its own before/after delta.
"""

import json
from pathlib import Path

import torch

from . import task
from .spec import TaskSpec


def _generate_batch(model, tokenizer, inputs, spec, device, max_new_tokens):
    prompts = [
        tokenizer.apply_chat_template(
            task.student_messages(spec, t),
            add_generation_prompt=True,
            enable_thinking=False,
            tokenize=False,
        )
        for t in inputs
    ]
    enc = tokenizer(prompts, return_tensors="pt", padding=True, padding_side="left")
    enc = {k: v.to(device) for k, v in enc.items()}
    with torch.no_grad():
        out = model.generate(
            **enc,
            do_sample=False,
            max_new_tokens=max_new_tokens,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        )
    continuations = out[:, enc["input_ids"].shape[1]:]
    return tokenizer.batch_decode(continuations, skip_special_tokens=True)


def _eval_model(model_path, rows, cfg, spec, label: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = cfg["student"]["device"]
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_path, dtype=torch.bfloat16, attn_implementation="sdpa"
    ).to(device)
    model.eval()

    fields = spec.output_fields()
    predictions, records = [], []
    batch = 16
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        texts = _generate_batch(
            model, tokenizer, [r[spec.input_field] for r in chunk], spec, device,
            cfg["eval"]["max_new_tokens"],
        )
        for row, text in zip(chunk, texts):
            parsed, reason = task.parse_response(spec, text)
            predictions.append(parsed)
            records.append({
                spec.input_field: row[spec.input_field],
                "reference": {f: row[f] for f in fields},
                "prediction": parsed,
                "parse_error": reason,
                "raw": text,
            })
        print(f"eval[{label}]: {min(i + batch, len(rows))}/{len(rows)}", flush=True)

    del model
    torch.cuda.empty_cache()
    refs = [{f: r[f] for f in fields} for r in rows]
    return task.score(spec, predictions, refs), records


def evaluate(cfg: dict, run_dir: Path) -> dict:
    spec = TaskSpec.load(run_dir / "spec.json")
    rows = [json.loads(l) for l in open(run_dir / "holdout.jsonl", encoding="utf-8")]

    base_scores, base_records = _eval_model(
        cfg["student"]["hf_path"], rows, cfg, spec, "base"
    )
    tuned_scores, tuned_records = _eval_model(
        run_dir / "merged", rows, cfg, spec, "tuned"
    )

    report = {"base": base_scores, "tuned": tuned_scores}
    (run_dir / "eval_report.json").write_text(json.dumps(report, indent=2))
    with open(run_dir / "predictions.jsonl", "w", encoding="utf-8") as f:
        for label, records in (("base", base_records), ("tuned", tuned_records)):
            for rec in records:
                f.write(json.dumps({"model": label, **rec}) + "\n")

    print("eval: " + json.dumps(report, indent=2), flush=True)
    return report
