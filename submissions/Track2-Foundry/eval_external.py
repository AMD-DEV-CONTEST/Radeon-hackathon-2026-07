"""Evaluate a trained student against the FIXED policy-labeled holdout.

The fixture (eval_fixtures/triage-100/) is the 100-ticket holdout that
was blind-annotated against the policy text — an external ground-truth
test set independent of whichever teacher generated the training data.
Reference comparison: the July-18 student (30B teacher) scored 0.95
exact against these labels.

Usage:
  python eval_external.py --config configs/cloud_radeon_q36.toml \
      --run-dir runs/slice-<new> \
      --fixture eval_fixtures/triage-100
"""

import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--fixture", default="eval_fixtures/triage-100")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from foundry import config as config_mod, task
    from foundry.evaluate import _generate_batch
    from foundry.spec import TaskSpec

    cfg = config_mod.load(args.config)
    run_dir = Path(args.run_dir)
    fixture = Path(args.fixture)
    spec = TaskSpec.load(run_dir / "spec.json")

    tickets = [json.loads(l)[spec.input_field]
               for l in open(fixture / "holdout.jsonl", encoding="utf-8")]
    labels = {r["idx"]: r for r in
              (json.loads(l) for l in open(fixture / "policy_labels.jsonl",
                                           encoding="utf-8"))}
    refs = [{f: labels[i][f] for f in spec.output_fields()}
            for i in range(len(tickets))]

    device = cfg["student"]["device"]
    tokenizer = AutoTokenizer.from_pretrained(run_dir / "merged")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        run_dir / "merged", dtype=torch.bfloat16, attn_implementation="sdpa"
    ).to(device)
    model.eval()

    predictions = []
    for i in range(0, len(tickets), 16):
        chunk = tickets[i:i + 16]
        texts = _generate_batch(model, tokenizer, chunk, spec, device,
                                cfg["eval"]["max_new_tokens"])
        predictions += [task.parse_response(spec, t)[0] for t in texts]
        print(f"external eval: {min(i + 16, len(tickets))}/{len(tickets)}",
              flush=True)

    scores = task.score(spec, predictions, refs)
    ambiguous = [i for i in range(len(tickets)) if labels[i].get("ambiguous")]
    keep = [i for i in range(len(tickets)) if i not in ambiguous]
    scores_unambig = task.score(
        spec, [predictions[i] for i in keep], [refs[i] for i in keep])
    report = {"vs_policy_truth": scores,
              "vs_policy_truth_unambiguous_only": scores_unambig,
              "reference_july18_student": {"exact": 0.95, "unambiguous": 1.00}}
    (run_dir / "external_eval.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
