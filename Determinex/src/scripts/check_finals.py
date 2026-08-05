import json
import os
from pathlib import Path

_corpus_dir = (
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "corpus"
    / "real_scale"
)

finals = [f for f in os.listdir(_corpus_dir) if "final" in f and f.endswith(".jsonl")]
for fname in sorted(finals)[:10]:
    path = os.path.join(_corpus_dir, fname)
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    obj = json.loads(lines[0])
    tp = obj["meta"]["type"]
    print(f"{fname}: {len(lines):,} lines, type={tp}")
