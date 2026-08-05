import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

DIR = str(
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "corpus"
    / "real_scale"
)
seen = set()
type_counts = defaultdict(int)
total = 0

for f in sorted(os.listdir(DIR)):
    if not f.endswith(".jsonl"):
        continue
    for line in open(os.path.join(DIR, f), encoding="utf-8"):
        obj = json.loads(line)
        k = hashlib.md5(
            (obj.get("instruction", "") + obj.get("output", ""))[:600].encode()
        ).hexdigest()
        if k in seen:
            continue
        seen.add(k)
        total += 1
        meta = obj.get("meta", {})
        t = meta.get("type", "unknown")
        type_counts[t] += 1

print(f"TOTAL UNIQUE: {total:,}")
print()
print("=== BY TYPE ===")
for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
    marker = "  OK" if c >= 5000 else " LOW" if c >= 2000 else " !!!"
    print(f"  {t:25s}: {c:>7,}{marker}")
