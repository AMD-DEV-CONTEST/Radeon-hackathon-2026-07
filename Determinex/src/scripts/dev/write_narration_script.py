#!/usr/bin/env python3
"""write_narration_script.py — the record-ready narration script, for a human voice.

Ryan: "that voice on the video is horrible ... if you give me the script i can record it and
you can chop it and place it."

Generates one markdown file listing every line to record, the filename to save it as, and how
long the synthetic stand-in runs so the effort is predictable.

Written as a FILE rather than a shell heredoc on purpose: the first version was a heredoc and
`C:\\tmp\\vo\\` came out of it as a literal TAB followed by a vertical tab, because the
backslashes were collapsed before Python parsed the string. Paths below use forward slashes,
which Windows accepts everywhere and which no shell layer can mangle.

    python scripts/dev/write_narration_script.py
"""

from __future__ import annotations

import importlib.util
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path.home() / "OneDrive/Desktop/DETERMINEX-UPLOAD/NARRATION_SCRIPT.md"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dur(path: Path) -> float | None:
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    unified = _load("build_unified_video")
    showcase = _load("build_showcase_video")

    L: list[str] = []
    L.append("# Narration script — record these, I will place them")
    L.append("")
    L.append("Save each take at the **exact filename** given. Mono is fine. wav, mp3, m4a, ogg")
    L.append("or flac all work — anything that is not already wav gets converted automatically.")
    L.append("")
    L.append("**Put them in:** `C:/tmp/vo/`")
    L.append("")
    L.append("Read at a normal pace. You do **not** need to match the timings below — the")
    L.append("builder stretches or scrolls the footage to fit whatever length your take is, so a")
    L.append("longer, more natural read costs nothing and needs no re-timing.")
    L.append("")
    L.append("A missing file falls back to the synthetic voice **for that line only**, so you can")
    L.append("record a few at a time and the video is never broken in between.")
    L.append("")
    L.append("---")
    L.append("")

    total = 0.0
    L.append("## MAIN DEMO — `DEMO_MAIN_2026-08-04.mp4`")
    L.append("")
    for key, _note, speech in unified.SECTIONS:
        d = _dur(Path("C:/tmp/narration2") / f"u{key}.wav")
        total += d or 0.0
        L.append(f"### Section {key} → save as `C:/tmp/vo/main_{key}.wav`")
        if d:
            L.append(f"*synthetic stand-in runs {d:.0f}s*")
        L.append("")
        L.append(speech)
        L.append("")
    L.append(f"*Main demo: {len(unified.SECTIONS)} takes, about {total / 60:.1f} min of speech.*")
    L.append("")
    L.append("---")
    L.append("")

    total_s = 0.0
    L.append("## PRODUCT SHOWCASE — `PRODUCT_SHOWCASE_2026-08-04.mp4`")
    L.append("")
    for member, (_note, speech) in showcase.SAY.items():
        d = _dur(Path("C:/tmp/narration3") / f"s_{member}.wav")
        total_s += d or 0.0
        L.append(f"### {member} → save as `C:/tmp/vo/show_{member}.wav`")
        if d:
            L.append(f"*synthetic stand-in runs {d:.0f}s*")
        L.append("")
        L.append(speech)
        L.append("")
    L.append(f"*Showcase: {len(showcase.SAY)} takes, about {total_s / 60:.1f} min of speech.*")
    L.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  main:     {len(unified.SECTIONS)} takes, {total / 60:.1f} min")
    print(f"  showcase: {len(showcase.SAY)} takes, {total_s / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
