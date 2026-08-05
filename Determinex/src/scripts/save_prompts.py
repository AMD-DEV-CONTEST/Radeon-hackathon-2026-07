"""
save_prompts.py — Write per-language prompt files to C:/tmp/prompts/
Creates 4 files: prompt_rust.txt, prompt_go.txt, prompt_python.txt, prompt_typescript.txt
Each file is a self-contained prompt for one model run.
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from micro_eval import CONCEPTS
from micro_eval_extra import EXTRA_CONCEPTS

ALL_CONCEPTS = {**CONCEPTS, **EXTRA_CONCEPTS}
OUT_DIR = Path("C:/tmp/prompts")
OUT_DIR.mkdir(parents=True, exist_ok=True)

LANGS = ["rust", "go", "python", "typescript"]

for lang in LANGS:
    probes = []
    for concept_key, concept in ALL_CONCEPTS.items():
        if concept["lang"] != lang:
            continue
        for probe in concept["probes"]:
            probes.append(
                {
                    "concept_key": concept_key,
                    "probe_id": probe["id"],
                    "lang": lang,
                    "fn_name": probe["fn_name"],
                    "system": concept["system"],
                    "prompt": probe["prompt"],
                }
            )

    out_path = Path(
        f"${{DETERMINEX_MODELS_DIR:-~/determinex-models}}/corpus/batch_MODEL_{lang}.json"
    )

    lines = [
        "You are generating a training corpus for a code-generation AI.",
        "",
        f"Solve all {len(probes)} {lang.upper()} coding tasks below.",
        "",
        "STRICT RULES:",
        "- Output ONLY a valid JSON array — nothing before or after it",
        f'- Each element: {{"concept_key": "...", "probe_id": "...", "lang": "{lang}", "code": "..."}}',
        '- The "code" field: raw code string only — NO markdown fences, NO explanation',
    ]

    if lang == "rust":
        lines += [
            "- Rust: complete `fn name(...) -> ... { ... }` block including any use imports needed",
            "- Do NOT include fn main()",
        ]
    elif lang == "go":
        lines += [
            "- Go: complete `func name(...) ... { ... }` block only",
            "- Do NOT include package declaration or import statements",
        ]
    elif lang == "python":
        lines += [
            "- Python: complete `def name(...):` function, including any needed imports inside the function or at top",
        ]
    elif lang == "typescript":
        lines += [
            "- TypeScript: complete function (and any required type definitions above it)",
            "- Do NOT include a main() call",
        ]

    lines += [
        "",
        "Replace MODEL in the output filename with the actual model name you are.",
        f"Write the JSON array to: {out_path}",
        "",
        "TASKS:",
        "",
    ]

    for i, p in enumerate(probes):
        lines.append(f"### Task {i + 1}/{len(probes)}")
        lines.append(f"concept_key: {p['concept_key']}")
        lines.append(f"probe_id: {p['probe_id']}")
        lines.append(f"function_name: {p['fn_name']}")
        lines.append(f"task: {p['prompt']}")
        lines.append("")

    content = "\n".join(lines)
    out_file = OUT_DIR / f"prompt_{lang}.txt"
    out_file.write_text(content, encoding="utf-8")
    print(f"  Wrote {len(probes)} {lang} tasks → {out_file}  ({len(content) // 1000}KB)")

print(f"\nAll prompts saved to {OUT_DIR}")
print("Open each file, copy contents, paste into the AI service.")
print("After each run, say which model + language is done.")
