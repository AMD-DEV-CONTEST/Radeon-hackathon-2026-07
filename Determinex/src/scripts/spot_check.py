import json
import os
from pathlib import Path

OUT = str(
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "corpus"
    / "real_scale"
)

path = os.path.join(OUT, "multi_turn_fill_v2.jsonl")
python_with_slashslash = 0
total_python = 0
with open(path, encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        if obj["meta"]["lang"] == "python":
            total_python += 1
            out = obj["output"]
            in_block = False
            for row in out.split("\n"):
                s = row.strip()
                if s.startswith("```python"):
                    in_block = True
                elif s == "```":
                    in_block = False
                elif in_block and s.startswith("//"):
                    python_with_slashslash += 1
                    break

print(
    f"multi_turn_fill_v2: {total_python} python examples, {python_with_slashslash} with // in python blocks"
)

# Count per file
mt_files = []
for fn in os.listdir(OUT):
    if "multi_turn" in fn and fn.endswith(".jsonl"):
        count = sum(1 for _ in open(os.path.join(OUT, fn), encoding="utf-8"))
        mt_files.append((fn, count))
for fn, c in sorted(mt_files):
    print(f"  {fn}: {c}")
print(f"  TOTAL: {sum(c for _, c in mt_files)}")

# Also verify version_migration files parse cleanly
for fn in ["version_migration_v1.jsonl", "version_migration_v2.jsonl"]:
    path = os.path.join(OUT, fn)
    ok, bad = 0, 0
    has_arrow = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ok += 1
                if "->" not in json.dumps(obj) and "\u2192" in json.dumps(obj):
                    has_arrow += 1
            except Exception:
                bad += 1
    print(f"  {fn}: {ok} ok, {bad} bad, {has_arrow} still have unicode arrow")
