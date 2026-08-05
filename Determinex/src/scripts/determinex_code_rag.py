#!/usr/bin/env python3
"""determinex_code_rag -- a retrieval index over high-quality CODEBASES (source + examples) so the
BUILDER can retrieve real, idiomatic example code (how a clean tool implements X). This is the right
home for raw source (the symptom->fix distiller, determinex_pb_absorb, rejects it as code-diff noise).

Pipeline: git-clone --depth 1 a curated repo list -> index code files by SYMBOL (fn/func/def/class/
struct names) + keyword -> retrieve(query) returns the most relevant files + snippets. Keyword/
symbol based (no embeddings) -> free + fast + local. Clones live on T: (big); the index is a small
JSON in the repo. Public repos, local index -> private + free.

Usage:
  determinex_code_rag.py --clone     # git-clone the repo list (depth 1) to T:/determinex-coderag
  determinex_code_rag.py --index     # (re)build the symbol/keyword index
  determinex_code_rag.py --retrieve "how to parse argv flags in rust"   # query
  determinex_code_rag.py --add-pb    # append the PB tools' upstream repos to the clone set
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Clones live here: T: on Windows (local), /root/determinex-coderag on the box (Linux). Override with
# DETERMINEX_CODERAG. The box builds its OWN bounded code-RAG (the curated refs) by cloning from GitHub.
CODE_DIR = Path(
    os.environ.get("DETERMINEX_CODERAG")
    or ("T:/determinex-coderag" if os.name == "nt" else "/root/determinex-coderag")
)
INDEX = ROOT / "corpus" / "programbench" / "code_rag_index.json"
REPO_LIST = ROOT / "corpus" / "programbench" / "ingest" / "_code_repos.txt"

# Curated idiomatic reference implementations (clean, well-tested; many are PB tools too).
REPOS = [
    "https://github.com/BurntSushi/ripgrep",
    "https://github.com/sharkdp/fd",
    "https://github.com/sharkdp/bat",
    "https://github.com/sharkdp/hyperfine",
    "https://github.com/clap-rs/clap",
    "https://github.com/serde-rs/serde",
    "https://github.com/BurntSushi/xsv",
    "https://github.com/ajeetdsouza/zoxide",
    "https://github.com/XAMPPRocky/tokei",
    "https://github.com/dandavison/delta",
    "https://github.com/starship/starship",
    "https://github.com/junegunn/fzf",
    "https://github.com/spf13/cobra",
    "https://github.com/charmbracelet/bubbletea",
    "https://github.com/tldr-pages/tldr",
]
_EXTS = {".rs", ".go", ".c", ".h", ".cpp", ".hpp", ".py", ".js", ".ts"}
_SKIP = ("/target/", "/node_modules/", "/.git/", "/vendor/", "/dist/", "/build/")
_SYM = re.compile(r"\b(fn|func|def|class|struct|impl|type|interface)\s+([A-Za-z_][A-Za-z0-9_]{2,})")


def _repos() -> list[str]:
    repos = list(REPOS)
    if REPO_LIST.exists():
        repos += [
            ln.strip()
            for ln in REPO_LIST.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith("http")
        ]
    return sorted(set(repos))


def clone() -> dict:
    CODE_DIR.mkdir(parents=True, exist_ok=True)
    repos = _repos()
    cloned = skipped = failed = 0
    for url in repos:
        name = url.rstrip("/").split("/")[-1]
        d = CODE_DIR / name
        if d.exists():
            skipped += 1
            continue
        try:
            r = subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet", url, str(d)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0:
                cloned += 1
                print(f"  cloned {name}")
            else:
                failed += 1
                print(f"  clone FAILED {name}: {(r.stderr or '')[:80]}")
        except Exception as e:
            failed += 1
            print(f"  clone ERROR {name}: {e}")
    return {"cloned": cloned, "skipped": skipped, "failed": failed, "of": len(repos)}


def build_index() -> dict:
    idx: dict[str, list[str]] = {}
    files = 0
    if not CODE_DIR.exists():
        return {"files": 0, "symbols": 0, "note": "no clones yet (run --clone)"}
    for f in CODE_DIR.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in _EXTS:
            continue
        sp = str(f).replace("\\", "/")
        if any(x in sp for x in _SKIP):
            continue
        try:
            if f.stat().st_size > 500_000:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        files += 1
        rel = str(f.relative_to(CODE_DIR))
        for m in _SYM.finditer(text):
            sym = m.group(2).lower()
            lst = idx.setdefault(sym, [])
            if rel not in lst and len(lst) < 25:
                lst.append(rel)
    INDEX.write_text(
        json.dumps({"root": str(CODE_DIR), "files": files, "symbols": idx}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"files": files, "symbols": len(idx)}


def retrieve(query: str, k: int = 8, exclude: str = "") -> list[dict]:
    """Return the code files/snippets most relevant to `query` (symbol/keyword overlap). `exclude`
    skips files under a repo dir -- pass the tool being reimplemented so we NEVER hand back its OWN
    source (that would be the answer-key / gaming). Examples are TECHNIQUE reference from OTHERS."""
    if not INDEX.exists():
        return []
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    root = Path(data.get("root", str(CODE_DIR)))
    idx = data.get("symbols", {})
    excl = exclude.lower().strip()
    toks = set(re.findall(r"[a-z_][a-z0-9_]{2,}", query.lower()))
    hits: dict[str, int] = {}
    for t in toks:
        for rel in idx.get(t, []):
            if excl and rel.replace("\\", "/").lower().startswith(excl + "/"):
                continue  # never return the tool's OWN source
            hits[rel] = hits.get(rel, 0) + 1
    out = []
    for rel, score in sorted(hits.items(), key=lambda kv: -kv[1])[:k]:
        try:
            out.append(
                {
                    "file": rel,
                    "score": score,
                    "snippet": (root / rel).read_text(encoding="utf-8", errors="replace")[:1500],
                }
            )
        except Exception:
            continue
    return out


def add_pb_repos() -> dict:
    """Append the PB tools' upstream repos (owner/repo from the corpus) to the clone set."""
    repos = set()
    ovr = ROOT / "corpus" / "programbench" / "per_tool_overrides"
    if ovr.exists():
        for d in ovr.iterdir():
            if not d.is_dir():
                continue
            m = re.match(r"([a-z0-9_-]+)__([a-z0-9_.-]+?)(?:\.[0-9a-f]{7,8})?$", d.name, re.I)
            if m:
                repos.add(f"https://github.com/{m.group(1)}/{m.group(2)}")
    REPO_LIST.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        set(REPO_LIST.read_text(encoding="utf-8").splitlines()) if REPO_LIST.exists() else set()
    )
    allrepos = sorted(existing | repos)
    REPO_LIST.write_text("\n".join(r for r in allrepos if r.strip()), encoding="utf-8")
    return {"pb_repos": len(repos), "total_in_list": len(allrepos)}


def main() -> int:
    if "--clone" in sys.argv:
        print(f"clone: {clone()}")
    elif "--index" in sys.argv:
        print(f"index: {build_index()}")
    elif "--add-pb" in sys.argv:
        print(f"add-pb: {add_pb_repos()}")
    elif "--retrieve" in sys.argv:
        q = sys.argv[sys.argv.index("--retrieve") + 1]
        for r in retrieve(q):
            print(f"  [{r['score']}] {r['file']}")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
