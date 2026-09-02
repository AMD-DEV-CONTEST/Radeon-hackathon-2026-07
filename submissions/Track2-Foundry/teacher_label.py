"""Label a set of inputs with one teacher — for teacher head-to-head audits.

Serves the given GGUF, labels each input per the spec's seed documents
(full corpus in context, temperature 0), writes JSONL of
{input, <output fields...>}.

Usage:
  python teacher_label.py --config <cfg> --gguf models/teacher/<x>.gguf \
      --spec specs/expense-routing-v2.json \
      --inputs runs/<pilot>/accepted.jsonl --n 20 --out labels_30b.jsonl
"""

import argparse
import json
from pathlib import Path

from foundry import config as config_mod, task
from foundry.config import REPO_ROOT
from foundry.datagen import load_seed_docs
from foundry.spec import TaskSpec
from foundry.teacher import TeacherClient, start_server, stop_server

PORT = 8126

PROMPT = """Here is the reference material:

---
{seeds}
---

Assign labels to this {noun} exactly per the reference material's rules
(apply precedence rules where several match).

{noun}: {text}

Respond with a single JSON object: {schema}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gguf", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = config_mod.load(args.config)
    spec = TaskSpec.load(args.spec)
    seeds = "\n\n".join(t for _, t in load_seed_docs(spec.seed_docs, REPO_ROOT))
    rows = [json.loads(l) for l in open(args.inputs, encoding="utf-8")][: args.n]

    proc = start_server(cfg["teacher"]["server_exe"], args.gguf, PORT,
                        n_gpu_layers=99, parallel=4, ctx_per_slot=8192)
    try:
        client = TeacherClient(f"http://127.0.0.1:{PORT}/v1")
        with open(args.out, "w", encoding="utf-8") as f:
            for i, row in enumerate(rows):
                text = client.chat(
                    [{"role": "user", "content": PROMPT.format(
                        seeds=seeds, noun=spec.example_noun,
                        text=row[spec.input_field],
                        schema=spec.schema_line())}],
                    temperature=0.0, max_tokens=256, json_mode=True,
                    chat_template_kwargs=cfg["teacher"].get(
                        "chat_template_kwargs"),
                )
                parsed, reason = task.parse_response(spec, text)
                f.write(json.dumps({
                    spec.input_field: row[spec.input_field],
                    "labels": parsed, "parse_error": reason}) + "\n")
                print(f"labeled {i + 1}/{len(rows)}", flush=True)
    finally:
        stop_server(proc)


if __name__ == "__main__":
    main()
