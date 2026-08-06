import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
paragraphs = [part.strip() for part in (ROOT / "docs" / "DEMO_NARRATION.txt").read_text().split("\n\n") if part.strip()]
sentences = []
for paragraph in paragraphs:
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        sentence = sentence.strip()
        if not sentence:
            continue
        words = sentence.split()
        if len(words) <= 26:
            sentences.append(sentence)
            continue
        clauses = re.split(r"(?<=[,;:])\s+", sentence)
        current = []
        for clause in clauses:
            clause_words = clause.split()
            if current and len(current) + len(clause_words) > 20:
                sentences.append(" ".join(current))
                current = []
            current.extend(clause_words)
        if current:
            sentences.append(" ".join(current))
cues = []
for sentence in sentences:
    lines = textwrap.wrap(sentence, width=42, break_long_words=False, break_on_hyphens=False)
    cues.extend("\n".join(lines[index : index + 2]) for index in range(0, len(lines), 2))

duration = 235.92
weights = [len(part.split()) for part in cues]
total = sum(weights)


def stamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


cursor = 0.0
blocks = []
for index, (cue, weight) in enumerate(zip(cues, weights), 1):
    end = duration if index == len(cues) else cursor + duration * weight / total
    blocks.append(f"{index}\n{stamp(cursor)} --> {stamp(end)}\n{cue}\n")
    cursor = end

(ROOT / "demo" / "DEMO_SUBTITLES.srt").write_text("\n".join(blocks), encoding="utf-8")
(ROOT / "docs" / "DEMO_SUBTITLES.srt").write_text("\n".join(blocks), encoding="utf-8")
print(f"wrote {len(blocks)} subtitle blocks through {stamp(cursor)}")
