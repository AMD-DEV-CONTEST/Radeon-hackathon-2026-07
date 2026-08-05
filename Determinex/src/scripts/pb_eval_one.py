import collections
import json
import sys

import determinex_pb_autofix as AF
from pb_eval_unified import run_local_eval

slug = sys.argv[1]
out = f"corpus/programbench/per_tool_overrides/{slug}/{slug}.eval.json"


def _score(path):
    try:
        dd = json.load(open(path))
        tr = dd.get("test_results", [])
        return collections.Counter(t.get("status") for t in tr).get("passed", 0), len(tr)
    except Exception:
        return (0, 0)


# corpus cycle -- capture BEFORE score (previous eval) before it is overwritten
bp, bt = _score(out)

tb = AF.pack_submission(slug)
d = run_local_eval(slug, tb) or {}
json.dump(d, open(out, "w"))
c = collections.Counter(t.get("status") for t in d.get("test_results", []))
ap, at = c.get("passed", 0), len(d.get("test_results", []))
print("PB_EVAL", slug, dict(c), "total", at)

# corpus cycle END SHOT -- every build segment auto-ends with a corpus shot: point-out +
# auto-CORRECT on regression. (Rich INSERTs come from the agent via build_cycle end --change.)
try:
    from determinex_pb_corpus_verify import verify

    if bt:  # only when there is a prior score to compare against
        r = verify(slug, f"{bp}/{bt}", f"{ap}/{at}", None, None, None)
        print(
            "CORPUS_END_SHOT",
            slug,
            r["direction"],
            "| corrected:",
            r["corrected"],
            "| inserted:",
            r["inserted"],
        )
except Exception as e:
    print("CORPUS_END_SHOT_ERR", repr(e))
