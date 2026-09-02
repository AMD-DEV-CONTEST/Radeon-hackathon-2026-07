import json
import os
from collections import defaultdict
from pathlib import Path

DIR = str(
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "corpus"
    / "real_scale"
)
type_counts = defaultdict(int)
total = 0

for f in sorted(os.listdir(DIR)):
    if not f.endswith(".jsonl"):
        continue
    for line in open(os.path.join(DIR, f), encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += 1
        meta = obj.get("meta", {})
        t = meta.get("type", "unknown")
        type_counts[t] += 1

print(f"TOTAL RAW: {total:,}")
print()
print("=== BY TYPE (raw count, no dedup) ===")
for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
    marker = "  OK" if c >= 5000 else " LOW" if c >= 2000 else " !!!"
    print(f"  {t:25s}: {c:>7,}{marker}")

# Count types that are OK vs not
ok = sum(1 for c in type_counts.values() if c >= 5000)
low = sum(1 for c in type_counts.values() if c < 5000)
print(f"\nTypes at 5k+: {ok}")
print(f"Types below 5k: {low}")
below = {t: c for t, c in type_counts.items() if c < 5000}
if below:
    print("\nBelow 5k types that need boost:")
    for t, c in sorted(below.items(), key=lambda x: -x[1]):
        need = 5000 - c
        print(f"  {t:25s}: {c:>6,} (need {need:,} more)")
