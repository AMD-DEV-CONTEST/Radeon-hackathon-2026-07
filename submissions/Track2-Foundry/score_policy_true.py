"""Score teacher labels and student predictions against independent
policy-true labels (blind re-annotation of the holdout against the seed
policy; see runs/<run>/policy_labels.jsonl, rationale per ticket).

Usage: python score_policy_true.py --run-dir runs/slice-20260718-052618
"""

import argparse
import json
from pathlib import Path


def score(preds, refs, fields):
    n = len(refs)
    valid = sum(1 for p in preds if p is not None)
    out = {"n": n, "answered": valid}
    for f in fields:
        out[f"{f}_acc"] = round(
            sum(1 for p, r in zip(preds, refs) if p and p[f] == r[f]) / n, 3)
    out["exact"] = round(
        sum(1 for p, r in zip(preds, refs)
            if p and all(p[f] == r[f] for f in fields)) / n, 3)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    run = Path(args.run_dir)

    fields = ["category", "priority"]
    policy = {r["idx"]: r for r in
              (json.loads(l) for l in open(run / "policy_labels.jsonl",
                                           encoding="utf-8"))}
    holdout = [json.loads(l) for l in open(run / "holdout.jsonl",
                                           encoding="utf-8")]
    assert len(holdout) == len(policy), "label/holdout count mismatch"

    preds = {"base": [None] * len(holdout), "tuned": [None] * len(holdout)}
    counters = {"base": 0, "tuned": 0}
    for line in open(run / "predictions.jsonl", encoding="utf-8"):
        rec = json.loads(line)
        model = rec["model"]
        preds[model][counters[model]] = rec["prediction"]
        counters[model] += 1

    refs = [policy[i] for i in range(len(holdout))]
    teacher = [{f: row[f] for f in fields} for row in holdout]

    report = {
        "labeling_protocol": (
            "100 holdout inputs re-labeled against seeds/triage_policy.md, "
            "blind to teacher labels and model outputs; per-ticket "
            "rationales in policy_labels.jsonl; ambiguous tickets flagged "
            "with the defensible alternative"),
        "ambiguous_count": sum(1 for r in refs if r.get("ambiguous")),
        "vs_policy": {
            "teacher_30B": score(teacher, refs, fields),
            "student_tuned": score(preds["tuned"], refs, fields),
            "student_base": score(preds["base"], refs, fields),
        },
    }

    # variant: ambiguous excluded
    keep = [i for i, r in enumerate(refs) if not r.get("ambiguous")]
    refs_x = [refs[i] for i in keep]
    report["vs_policy_unambiguous_only"] = {
        "n": len(keep),
        "teacher_30B": score([teacher[i] for i in keep], refs_x, fields),
        "student_tuned": score([preds["tuned"][i] for i in keep], refs_x, fields),
    }

    # where teacher and policy disagree
    disagreements = [
        {"idx": i, "policy": {f: refs[i][f] for f in fields},
         "teacher": teacher[i],
         "ambiguous": bool(refs[i].get("ambiguous"))}
        for i in range(len(refs))
        if any(teacher[i][f] != refs[i][f] for f in fields)
    ]
    report["teacher_policy_disagreements"] = disagreements

    (run / "policy_true_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
