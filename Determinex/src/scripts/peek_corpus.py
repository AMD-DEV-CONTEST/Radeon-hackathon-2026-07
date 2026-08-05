import json
import os
from collections import Counter

langs = Counter()
topics = Counter()
types = Counter()
total = 0
sample_keys = None

files = ["data/corpus_generated.jsonl"]
gap_files = [
    os.path.join("scripts", f)
    for f in os.listdir("scripts")
    if f.startswith("gap_v") and f.endswith(".jsonl")
]
files.extend(gap_files)

for fname in files:
    try:
        with open(fname, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if sample_keys is None:
                        sample_keys = list(obj.keys())
                        print("KEYS:", sample_keys)
                        instruction = obj.get("instruction", obj.get("prompt", ""))
                        output = obj.get("output", obj.get("response", obj.get("completion", "")))
                        print("INSTRUCTION SAMPLE:", str(instruction)[:120])
                        print("OUTPUT SAMPLE:", str(output)[:120])
                        print()

                    # Try to detect language from instruction/output content
                    instruction = str(obj.get("instruction", obj.get("prompt", ""))).lower()
                    output = str(obj.get("output", obj.get("response", obj.get("completion", ""))))

                    # Language detection from keywords in instruction
                    lang = "unknown"
                    for kw, l in [
                        ("rust", "rust"),
                        ("golang", "go"),
                        (" go ", "go"),
                        ("python", "python"),
                        ("typescript", "typescript"),
                        ("javascript", "javascript"),
                        ("java ", "java"),
                        ("kotlin", "kotlin"),
                        ("swift", "swift"),
                        ("c++", "cpp"),
                        ("c#", "csharp"),
                        ("ruby", "ruby"),
                        ("haskell", "haskell"),
                        ("scala", "scala"),
                        ("clojure", "clojure"),
                        ("elixir", "elixir"),
                        ("erlang", "erlang"),
                        ("ocaml", "ocaml"),
                        ("fsharp", "fsharp"),
                        ("f#", "fsharp"),
                        ("cobol", "cobol"),
                        ("fortran", "fortran"),
                        ("pascal", "pascal"),
                        ("ada", "ada"),
                        ("prolog", "prolog"),
                        ("lisp", "lisp"),
                        ("zig", "zig"),
                        ("assembly", "asm"),
                        ("bash", "bash"),
                        ("powershell", "powershell"),
                        ("php", "php"),
                        ("lua", "lua"),
                        ("dart", "dart"),
                        ("r lang", "r"),
                        ("sql", "sql"),
                        ("graphql", "graphql"),
                        ("solidity", "solidity"),
                        ("wasm", "wasm"),
                    ]:
                        if kw in instruction:
                            lang = l
                            break

                    # Fallback: detect from output code markers
                    if lang == "unknown":
                        if "fn " in output and (
                            "let " in output or "impl " in output or "-> " in output
                        ):
                            lang = "rust"
                        elif "func " in output and (
                            "chan " in output or "goroutine" in output or ":=" in output
                        ):
                            lang = "go"
                        elif "def " in output and ("self" in output or "import " in output):
                            lang = "python"
                        elif "function " in output and ("const " in output or "=>" in output):
                            lang = "javascript"
                        elif "fn " in output:
                            lang = "rust_likely"
                        elif "func " in output:
                            lang = "go_likely"
                        elif "def " in output:
                            lang = "python_likely"

                    langs[lang] += 1
                    total += 1
                except Exception:
                    pass
    except FileNotFoundError:
        pass

print(f"\nTOTAL SCANNED: {total}")
print("\n--- DETECTED LANGUAGES ---")
for lang, count in langs.most_common(50):
    pct = (count / total * 100) if total else 0
    print(f"  {lang}: {count} ({pct:.1f}%)")
