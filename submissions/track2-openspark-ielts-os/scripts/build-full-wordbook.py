import csv
import json
import re
import sys
from pathlib import Path

source = Path(sys.argv[1])
root = Path(__file__).resolve().parent.parent
target = root / "data" / "wordbook.json"
wordbook = json.loads(target.read_text())
existing = {item["word"].strip().lower(): item for item in wordbook["words"]}

def number(value):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else 10_000_000
    except (TypeError, ValueError):
        return 10_000_000

def priority(row):
    tags = set((row.get("tag") or "").lower().split())
    exam = next((rank for rank, tag in enumerate(("ielts", "toefl", "ky", "cet6", "cet4")) if tag in tags), 5)
    dictionary = 0 if row.get("oxford") == "1" else 1 if number(row.get("collins")) < 10_000_000 else 2
    return exam, dictionary, min(number(row.get("bnc")), number(row.get("frq"))), row["word"]

candidates = {}
with source.open(encoding="utf-8", newline="") as handle:
    for row in csv.DictReader(handle):
        word = (row.get("word") or "").strip().lower()
        translation = (row.get("translation") or "").strip()
        if word in existing:
            phonetic = (row.get("phonetic") or "").strip()
            existing[word]["englishDefinition"] = (row.get("definition") or "").replace("\\n", "; ").strip()
            if not existing[word].get("phonetic") and phonetic:
                existing[word]["phonetic"] = f"/{phonetic}/"
            continue
        tags = set((row.get("tag") or "").lower().split())
        relevant = tags.intersection({"ielts", "toefl", "ky", "cet6", "cet4"}) or row.get("oxford") == "1" or number(row.get("collins")) < 10_000_000
        if not relevant or not translation or not re.fullmatch(r"[a-z][a-z'-]*", word):
            continue
        candidates.setdefault(word, row)

for row in sorted(candidates.values(), key=priority):
    if len(existing) >= 8000:
        break
    word = row["word"].strip().lower()
    tags = (row.get("tag") or "").lower().split()
    phonetic = (row.get("phonetic") or "").strip()
    existing[word] = {
        "word": word,
        "phonetic": f"/{phonetic}/" if phonetic else "",
        "definition": "；".join(part.strip() for part in row["translation"].splitlines() if part.strip()),
        "englishDefinition": (row.get("definition") or "").replace("\\n", "; ").strip(),
        "status": "新词",
        "memoryState": "new",
        "bookIndex": len(existing) + 1,
        "example": "",
        "ieltsExample": "",
        "source": "ECDICT · 考试高频词",
        "topic": next((tag.upper() for tag in ("ielts", "toefl", "ky", "cet6", "cet4") if tag in tags), "Academic"),
        "links": [],
    }

if len(existing) < 8000:
    raise SystemExit(f"Only {len(existing)} eligible words found")

words = list(existing.values())[:8000]

for index, item in enumerate(words, 1):
    item["bookIndex"] = index
wordbook["words"] = words
wordbook["book"].update({"id": "ielts-core-8000", "title": "雅思核心 8000 词", "total": 8000})
target.write_text(json.dumps(wordbook, ensure_ascii=False, indent=2) + "\n")
print("Built complete 8,000-word IELTS book with phonetics and Chinese definitions.")
