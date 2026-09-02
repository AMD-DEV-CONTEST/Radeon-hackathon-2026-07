import glob
import hashlib
import json
import os
from pathlib import Path

DIR = str(
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "corpus"
    / "real_scale"
)
seen = set()
lang = {}
for f in sorted(glob.glob(os.path.join(DIR, "*.jsonl"))):
    for line in open(f, encoding="utf-8"):
        if not line.strip():
            continue
        obj = json.loads(line)
        k = hashlib.md5(
            (obj.get("instruction", "") + obj.get("output", ""))[:600].encode()
        ).hexdigest()
        if k not in seen:
            seen.add(k)
            l = obj.get("meta", {}).get("lang", "unk")
            lang[l] = lang.get(l, 0) + 1
total = len(seen)
print("=== FINAL CORPUS STATS ===")
print("UNIQUE TOTAL:", total)
print("Target:       100000")
need = 100000 - total
print("Status:       DONE" if need <= 0 else "Need: " + str(need))
print()
print("Language distribution:")
for k, v in sorted(lang.items(), key=lambda x: -x[1]):
    print(" ", k, ":", v)
