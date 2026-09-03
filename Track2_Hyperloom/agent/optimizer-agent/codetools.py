"""
codetools.py — lets the agent MODIFY THE SOURCE and REBUILD, not just tune runtime flags.

On a blank stock stack the runtime levers run out fast; a real hacker changes the code. These tools
let the agent read the llama.cpp/ggml source, search it, edit it, and recompile — to make a model
load, add or fix a kernel, or tune the code for speed. Edits land in a git worktree (revertible), so
the agent can experiment and back out cleanly.

  read_source(path)              -> read a file (relative to the repo, or absolute)
  grep_source(pattern, glob)     -> search the codebase for where to change something
  edit_source(path, old, new)    -> exact-string replace in a file
  rebuild(targets)               -> recompile; returns success + any compiler errors
  revert_source(path)            -> git-checkout a file back to its committed state

Scoped to the repo the run points at (CODE_REPO). After any rebuild the agent must re-baseline and
revert if it regressed or broke correctness — same discipline as every other lever.
"""
import os, re, glob, subprocess, textwrap

REPO  = os.environ.get("CODE_REPO",  os.environ.get("HACK_REPO", "/home/jmonk/src/llama-main714"))
BUILD = os.environ.get("CODE_BUILD", "build-main714")
ENVSRC = os.environ.get("CODE_ENV", "/home/jmonk/src/mainline-llama.cpp-mxfp8/use-rocm714.env")

def _abs(p):
    return p if os.path.isabs(p) else os.path.join(REPO, p)

def _norm(s):
    return "\n".join(l.rstrip() for l in s.replace("\r\n", "\n").replace("\r", "\n").split("\n"))

def _tolerant_replace(text, old, new):
    """Aider/Cline-style tolerant search/replace: exact -> whitespace-normalized -> relative-indent.
    Weak models drift on whitespace/indent; exact match then rejects the edit and the model gives up.
    Returns (new_text, how) or (None, 'no-match')."""
    if old in text:
        return text.replace(old, new, 1), "exact"
    ntext, nold, nnew = _norm(text), _norm(old), _norm(new)
    if nold in ntext:
        return ntext.replace(nold, nnew, 1), "whitespace-normalized"
    # relative-indent: dedent the search block and slide a same-height window, comparing dedented
    dold = textwrap.dedent(nold).strip("\n")
    oldlines = dold.split("\n")
    n = len(oldlines)
    lines = ntext.split("\n")
    for i in range(len(lines) - n + 1):
        window = lines[i:i + n]
        if textwrap.dedent("\n".join(window)).strip("\n") == dold:
            base = window[0]
            indent = base[:len(base) - len(base.lstrip())]
            newlines = [(indent + l) if l.strip() else l for l in nnew.split("\n")]
            return "\n".join(lines[:i] + newlines + lines[i + n:]), "relative-indent"
    return None, "no-match"

CODE_TOOLS = [
    {"type": "function", "function": {
        "name": "grep_source",
        "description": "Search the source tree for a regex/text pattern. By DEFAULT returns a compact "
                       "{file: match_count} summary (use this to localize). Pass show_lines=true (with a "
                       "tight glob) to see the actual file:line matches once you know which file to open.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "glob":    {"type": "string", "description": "file glob, e.g. 'ggml/src/ggml-cuda/*.cu' (optional)"},
            "show_lines": {"type": "boolean", "description": "true = expand to file:line matches (default false)"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "read_source",
        "description": "Read a source file (relative to the repo or absolute). Optionally a line range "
                       "(keep it small, ~100 lines).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "edit_source",
        "description": "Modify source by search/replace. Matching is TOLERANT (whitespace + indentation "
                       "drift are OK) — you do NOT need an exact byte-for-byte match, just the right block. "
                       "For a small file it is often easier to use write_file (whole-file rewrite) instead. "
                       "Rebuild afterward.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}},
            "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Rewrite an ENTIRE file with new contents (creates it if missing). Prefer this over "
                       "edit_source for small files or when a search/replace keeps failing — regenerate the "
                       "whole file in one shot. Rebuild afterward.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "contents": {"type": "string"}},
            "required": ["path", "contents"]}}},
    {"type": "function", "function": {
        "name": "rebuild",
        "description": "Recompile the build after editing source. Returns success/failure and compiler errors. "
                       "Always re-baseline after a successful rebuild; revert if it regressed or broke correctness.",
        "parameters": {"type": "object", "properties": {
            "targets": {"type": "string", "description": "space-separated cmake targets (default: llama-bench)"}}}}},
    {"type": "function", "function": {
        "name": "revert_source",
        "description": "Undo edits to a file by checking it out from git (use when a change regressed or broke it).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]

def code_execute(fn, args):
    a = args or {}
    try:
        if fn == "grep_source":
            g = a.get("glob") or "**/*"
            files = glob.glob(os.path.join(REPO, g), recursive=True)
            pat, per_file = re.compile(a["pattern"]), {}
            for f in files[:6000]:
                if not os.path.isfile(f): continue
                try:
                    for i, ln in enumerate(open(f, errors="ignore"), 1):
                        if pat.search(ln):
                            per_file.setdefault(os.path.relpath(f, REPO), []).append((i, ln.strip()[:160]))
                except Exception: pass
            if not per_file:
                return {"matches": "no matches"}
            if a.get("show_lines"):
                out = [f"{f}:{i}: {t}" for f, hits in per_file.items() for i, t in hits[:20]]
                return {"matches": out[:40]}
            # default: compact file->count summary (SWE-agent: raw per-match dumps confuse the model)
            return {"summary": {f: len(h) for f, h in sorted(per_file.items(), key=lambda kv: -len(kv[1]))[:25]},
                    "note": "file:count summary. Re-run with show_lines=true and a tight glob to see the lines."}
        if fn == "read_source":
            p = _abs(a["path"])
            if not os.path.exists(p): return {"error": f"no such file {p}"}
            lines = open(p, errors="ignore").read().splitlines()
            s, e = a.get("start", 1), a.get("end", min(len(lines), 200))
            return {"path": a["path"], "lines": f"{s}-{e}",
                    "text": "\n".join(f"{i+1}\t{lines[i]}" for i in range(max(0, s-1), min(len(lines), e)))}
        if fn == "edit_source":
            p = _abs(a["path"])
            if not os.path.exists(p):
                return {"error": f"no such file {p} — use write_file to create it"}
            txt = open(p, errors="ignore").read()
            newtxt, how = _tolerant_replace(txt, a["old_string"], a["new_string"])
            if newtxt is None:
                return {"error": "search block not found even with tolerant (whitespace/indent) matching. "
                        "read_source the exact current text and retry, or use write_file to rewrite the whole file."}
            open(p, "w").write(newtxt)
            return {"edited": a["path"], "matched": how, "note": "rebuild to apply"}
        if fn == "write_file":
            p = _abs(a["path"])
            new = a["contents"]
            new_lines = new.count("\n") + 1
            # TRUNCATION GUARD: a weak model cannot regenerate a large file from context — it emits a
            # stub and silently deletes thousands of lines (this nuked ggml.c 8023->67). Refuse to
            # whole-file-rewrite an existing large file, and refuse any rewrite that shrinks a file
            # drastically. Force targeted edit_source instead.
            if os.path.exists(p):
                old_lines = sum(1 for _ in open(p, errors="ignore"))
                if old_lines > 400:
                    return {"error": f"REFUSED: {a['path']} has {old_lines} lines — too large to safely "
                            "rewrite whole. Use edit_source for a targeted search/replace on the exact "
                            "block you want to change. write_file is only for small/new files."}
                if new_lines < old_lines * 0.6 and old_lines > 40:
                    return {"error": f"REFUSED: rewrite would shrink {a['path']} from {old_lines} to "
                            f"{new_lines} lines (likely truncated). If you really mean to delete code use "
                            "edit_source on the specific lines; otherwise include the FULL file contents."}
            d = os.path.dirname(p)
            if d: os.makedirs(d, exist_ok=True)
            open(p, "w").write(new)
            return {"wrote": a["path"], "bytes": len(new), "lines": new_lines, "note": "rebuild to apply"}
        if fn == "rebuild":
            tgt = a.get("targets") or "llama-bench"
            cmd = (f"cd {REPO} && source {ENVSRC} >/dev/null 2>&1 && "
                   f"cmake --build {BUILD} --target {tgt} -j88 2>&1 | tail -40")
            out = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=1800).stdout
            ok = "error:" not in out.lower() and "Error" not in out
            errs = [l for l in out.splitlines() if re.search(r"error", l, re.I)][:8]
            return {"rebuilt": ok, "targets": tgt, "errors": errs or "none", "tail": out.splitlines()[-4:]}
        if fn == "revert_source":
            p = _abs(a["path"])
            subprocess.run(["bash", "-lc", f"cd {REPO} && git checkout -- {a['path']}"], timeout=60)
            return {"reverted": a["path"]}
    except subprocess.TimeoutExpired:
        return {"error": "timed out"}
    except Exception as e:
        return {"error": str(e)}
    return {"error": f"unknown code tool {fn}"}

CODE_PREAMBLE = (
    "You can MODIFY THE SOURCE CODE and REBUILD, not only tune runtime flags. When runtime levers run "
    "out, or a model will not load, or you want to change a kernel/constant for speed: grep_source to "
    "find the spot, read_source to understand it, edit_source to change it, rebuild to compile, then "
    "RE-BASELINE and keep only if it is faster/works AND correctness holds — revert_source otherwise. "
    "Editing code is a legitimate lever here. Be surgical: one change, rebuild, measure, keep or revert.")
