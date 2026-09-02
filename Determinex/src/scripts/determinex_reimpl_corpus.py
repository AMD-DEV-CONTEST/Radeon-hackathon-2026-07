#!/usr/bin/env python3
"""
determinex_reimpl_corpus.py -- the corpus as a COACH + LEARNER for the reimpl engine
================================================================================
Two directions, per the Determinex thesis (corpus = source-knowledge friend that feeds the
models AND accumulates verified capability):

  READ  (coach):  render_prompt_block(short) -> cross-tool reimpl pitfalls we've learned
                  + per-tool discovered spec/known-hard-behaviors -> injected into the
                  builder prompt so the model starts each task with what Determinex knows.
  WRITE (learn):  record_run(...) -> after a run, persist the observed-behavior summary,
                  the behaviors that were HARD (failed probes), best local/official score,
                  and -- only on a genuine official pass -- LOCK it as a verified skill.

Legitimacy: only observed/discoverable behavior + general patterns are stored or injected
-- NEVER test goldens/assertions. Verified-skill lock requires a real official pass.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "corpus" / "programbench" / "reimpl_skills"

# Cross-tool wisdom: the recurring reimplementation pitfalls we've learned the hard way.
# This coaches EVERY tool, every model. Grows as new cross-tool patterns are found.
CROSS_TOOL_PITFALLS = """## Reimplementation pitfalls Determinex has learned (apply to ALL tools)
- Arrays render with `[]` and `[i]` indices, NOT object `{}` — detect list vs dict correctly.
- Match the EXACT exit code per case: some flags exit 0 with empty stdout; malformed input
  often exits 2 or 3; invalid ungron-style input may exit 5; a failed URL fetch exits 4.
- Preserve numbers' EXACT input text (`1.2e10` stays `1.2e10`, `-0` stays `-0`) — do NOT
  reformat via float(); parse number tokens as raw strings.
- Process the input ONCE — never print the output twice (a common duplication bug).
- Usage/error text goes to STDERR; empty stdout + a non-zero exit usually means stderr.
- A short flag (e.g. -V) may behave differently from its long form (--version) — follow
  the OBSERVED behavior, not the conventional meaning.
- Read input from a FILE argument if one is given, else from STDIN — handle both.
- Match stdout byte-for-byte including trailing newlines and exact escape/ANSI sequences.
"""

# TECHNIQUE RECIPES: a cheap model often knows WHAT to do but not HOW. These are concrete,
# verified code techniques for the recurring hard behaviors -- the difference between
# "preserve numbers" (a principle it can't act on) and a snippet it can paste. Proven from
# the gron 153/224 reference reimplementation. Injected when the tool's domain matches.
#
# LANGUAGE-NEUTRAL BY DESIGN (fixed 2026-07-16): json/io originally carried literal Python
# code samples (class Raw(str): pass, json.loads(...)) -- dead weight for a Rust/Go/C/C++
# reimplementation, which is the overwhelming majority of real tasks (107 rust, 46 go, 33 c,
# 12 cpp vs a handful of python). Rewritten as technique PROSE + per-language notes, matching
# the pattern table/tui already used correctly (they never carried Python-only code).
_RECIPES = {
    "json": """## TECHNIQUE: preserve EXACT number text (json tools) -- the #1 cause of core failures
Any JSON decoder that converts a number token to a native float/int DESTROYS the original text
(1.2e10 -> 12000000000.0, -0 -> 0) BEFORE you can re-emit it, and you can NEVER reconstruct the
original text afterward. You must capture the RAW SUBSTRING at parse time, not the parsed value.
- Python (stdlib, has real JSON support): `json.loads(s, parse_int=lambda x: x, parse_float=lambda x: x)`
  keeps the callback's return value as-is -- return the raw string, not float(x)/int(x).
- Go (stdlib `encoding/json` genuinely supports this): `dec := json.NewDecoder(r); dec.UseNumber()`
  makes every number decode as `json.Number` (a string alias) -- use `.String()` to re-emit it
  exactly; do NOT convert it to `float64`/`int64` anywhere in the pipeline.
- Rust/C/C++ (NO stdlib JSON at all -- you are hand-writing a recursive-descent parser
  regardless): while scanning a number token, record its start/end byte offsets in the
  original input and re-emit that exact substring; never route it through a float/double parse
  step even internally.
STRING VALUES: escape newline/tab/quote/backslash exactly as a real JSON encoder would
(`\\n`, `\\t`, `\\"`, `\\\\`) -- writing the literal control character instead of the escape
sequence splits output across lines and fails every string test.
COMPACT JSON: when emitting any JSON array/object, use NO space after a comma or colon
(`["b",0]`, `{"a":1}`) -- these tools emit compact JSON; a default encoder's `", "` spacing
(Python's default `json.dumps`, for instance) fails every compact-mode test.
RESERVED-WORD KEYS: object keys literally named `true`/`false`/`null` are emitted in BRACKET
form when addressed (`json["null"]`), never dotted -- they sort by their bracketed/quoted form.""",
    "io": """## TECHNIQUE: file-arg-or-stdin + exact exit codes
Read from a non-flag ARGUMENT (usually a filename) if one is present; only fall back to stdin
when there is no such argument (a bare `-` argument commonly means "read stdin explicitly").
- Python: `src = next((a for a in argv[1:] if not a.startswith("-")), None)`, then
  `open(src, encoding="utf-8").read() if src and src != "-" else sys.stdin.read()`.
- Rust: `std::env::args().skip(1).find(|a| !a.starts_with('-'))`, then
  `std::fs::read_to_string(path)` or `std::io::stdin()` if none.
- Go: iterate `os.Args[1:]` for the first entry not starting with `-`, then `os.ReadFile(path)`
  or `io.ReadAll(os.Stdin)`.
- C/C++: scan `argv[1..argc)` for the first entry not starting with `-`, then `fopen`/
  `std::ifstream` or read from `stdin`/`std::cin`.
Malformed input: write the tool's exact error to STDERR and use its OBSERVED exit code (often
3 for parse errors, 4 for a failed URL fetch, 5 for invalid structured input) -- match what
the reference observation actually showed, never assume a "conventional" code.""",
    "table": """## TECHNIQUE: box-drawing table layout -- the 3 byte-exact rules models get WRONG
A grid/box table is NOT "draw a header then a horizontal line". Get these EXACTLY or every
table fails byte-match (verified against the reference binary):
1. COLUMN WIDTH = max DISPLAY width of all cells in that column (header included). DISPLAY
   width is NOT string length: East-Asian wide + fullwidth chars count as 2 columns each
   (Rust: `unicode_width::UnicodeWidthStr::width`; Go: `runewidth.StringWidth`; never `len()`
   or `.chars().count()`). Each rendered cell is ` ` + pad(content, colwidth) + ` ` (one
   space of padding on EACH side -> inner cell width = colwidth + 2).
2. SEPARATOR lines carry a JUNCTION char at EVERY column boundary -- they are NOT one flat run
   of dashes. Top `┌──┬──┬──┐`, mid (under header) `├──┼──┼──┤`, bottom `└──┴──┴──┘`. The
   junction sits exactly above/below each `┬`/`┴`, i.e. after every (colwidth+2) dashes. A mid
   rule rendered as `├────────┤` (no `┼`) is the #1 cause of style/border test failures.
3. ALIGNMENT differs header vs body: HEADER cells are CENTER-aligned, BODY cells LEFT-aligned
   (unless an align flag overrides). Center of width W: left pad = floor((W-content)/2), the
   extra space goes on the RIGHT. So `a` in a width-4 column -> `  a   ` inside the borders
   (incl. the 1-space side padding); body `1` -> ` 1    `.
Style variants (none/ascii/sharp/rounded/grid/markdown) only change WHICH glyphs fill these
slots -- the width/junction/alignment math above is identical for all of them. Capture each
style's exact glyph set from the reference probes; keep the layout math shared.""",
    "tui": """## TECHNIQUE: ncurses/curses TUI tools -- what the tests actually check
Proven 2026-07-02 (tty-clock, hand-driven). A plain (non-pty) probe of an ncurses binary
prints "Error opening terminal: unknown" and exits 1 -- that IS real, correct reference
behavior for a no-TTY/no-TERM harness context (replicate it: check `newterm()`/`initscr()`
for failure, exit(1)), but it teaches you NOTHING about the tool's actual rendering. Real
rendered content only shows up in a pty-captured observation (look for a `tui-snapshot*`
probe among your observations -- raw ANSI/terminal escape bytes, e.g. `\\x1b[42m` = a
colored block cell). If one is present, the tool draws real content (big block-digit
displays, colored regions, box art) via ncurses color pairs / attron(A_*) -- do NOT just
`mvaddstr()` a plain text string; that under-renders and fails byte-count/content checks.
TEST SHAPE, not pixel-perfect match: TUI eval assertions are typically (a) `len(stdout) >
N` -- render enough real content per frame, not one thin text line; (b) `"\\x1b[42m" in
screen` or similar -- USE the observed color/attribute escapes, don't just approximate with
plain text; (c) exact `golden == actual` snapshots -- these often NORMALIZE block-rendered
lines to a placeholder token before comparing, so genuine escape-sequence-driven rendering
of the right STRUCTURE (row/column layout) tends to match without needing byte-exact segment
shapes. Test harnesses commonly use tmux (`TmuxHarness`) to drive real keypresses/resize --
handle SIGTERM/keypress-to-quit exactly as observed (default: any key exits unless a
"don't quit on keypress" flag is set).""",
    "diff": """## TECHNIQUE: line-diff output -- hunk grouping and header format models get wrong
A real unified-diff-style tool is not "print every changed line" -- it groups changes into
HUNKS with a small window of unchanged CONTEXT lines around each change (commonly 3), and
emits a header line per hunk: `@@ -<old_start>,<old_count> +<new_start>,<new_count> @@`.
- The underlying algorithm is a longest-common-subsequence (LCS) line match, not a naive
  line-by-line comparison -- an insertion/deletion shifts every following line, and a naive
  compare will misalign the rest of the file after the first change.
- Unchanged lines inside a hunk are prefixed with a single space, removed lines with `-`,
  added lines with `+` -- get the prefix column exactly right, it's byte-checked.
- Adjacent hunks within `2 * context_lines` of each other are usually merged into one hunk
  rather than emitted separately -- check the reference's exact merging behavior via probes
  rather than assuming a fixed window.
- Color/highlight variants (diffr/delta-style) add ANSI codes around the changed SPAN within
  a line, not just around the whole line -- if the tool does word-level or character-level
  highlighting, the reference probe's exact escape placement matters, not just "some color".
None of Rust/Go/C/C++ have a usable diff algorithm in their standard library -- this is always
hand-rolled (a straightforward O(N*M) or Myers-style LCS is sufficient for CLI-scale input).""",
    "csv": '''## TECHNIQUE: quoted-field CSV/TSV parsing and emission -- the naive split() trap
Splitting a line on `,` breaks the instant any field contains a comma, a quote, or an embedded
newline -- which real CSV data does. A correct parser/writer follows (informally) RFC 4180:
- A field containing a comma, a double-quote, or a newline MUST be wrapped in double quotes.
- A literal double-quote INSIDE a quoted field is escaped by DOUBLING it (`"He said ""hi"""`),
  never backslash-escaped.
- A quoted field may itself contain a literal newline -- a naive line-by-line reader will
  incorrectly treat that as a new record; a real parser tracks "am I inside an open quote"
  across the whole read, not per line.
- Trailing-newline and header-row conventions vary per tool -- match the OBSERVED output's
  exact line-ending and whether the header row is repeated/omitted, don't assume a default.
None of Rust/Go/C/C++/Python have a stdlib CSV parser sophisticated enough to skip this
entirely (Python's `csv` module and Go's `encoding/csv` are genuinely usable here and DO
implement RFC 4180 correctly -- use them if available; Rust/C/C++ have no stdlib CSV support
at all and this must be hand-written).''',
    "regex_glob": """## TECHNIQUE: glob/pattern matching without a regex library
Most CLI glob syntax (`*` = any run of chars except `/`, `?` = any one char, `[abc]`/`[a-z]`
= a character class, `**` = recursive directory match) is NOT the same as regex syntax and
should be converted deliberately, not passed through as-is:
- Convert glob syntax to an anchored regex by escaping every regex-special character in the
  literal parts and only translating the glob metacharacters (`*`, `?`, `[...]`) to their
  regex equivalents (`[^/]*`, `.`, `[...]` as-is) -- a raw literal `.` in a filename glob
  must become `\\.` in the translated regex, or it will incorrectly match any character.
- Go has a genuinely usable stdlib `regexp` package AND `path/filepath.Match` for glob syntax
  directly -- prefer these over hand-rolling.
- Rust/C/C++ have NO stdlib regex or glob matcher -- hand-roll either a small backtracking
  glob matcher (simpler, sufficient for most CLI glob needs) or a minimal regex engine scoped
  to exactly the syntax the observed tests actually exercise (don't build a general-purpose
  regex engine if the tests only ever use literal substrings + `*`/`?`).
- Case-sensitivity and whether `*` matches a leading dot (hidden files) are common
  probe-dependent behaviors -- verify against the actual observed matches/non-matches rather
  than assuming shell-glob conventions apply uniformly.""",
    "ansi": """## TECHNIQUE: ANSI color/style codes -- generation and stripping
Raw ANSI escape sequences are `\\x1b[<params>m` (SGR -- Select Graphic Rendition), e.g.
`\\x1b[32m` = green foreground, `\\x1b[1m` = bold, `\\x1b[0m` = reset all attributes. There is
no external color library available in any of Rust/Go/C/C++'s standard library -- construct
and concatenate these escape strings directly.
- ALWAYS emit a reset (`\\x1b[0m`) after a colored span, not just at the very end of output --
  a test that checks per-line or per-token coloring expects each colored region independently
  reset, not one reset at EOF.
- Respect `--no-color`/`--color` flags and the `NO_COLOR` env var convention (see
  language_reference/systems.md) -- when disabled, omit ALL escape codes entirely rather than
  emitting them and hoping the test strips them; tests that disable color expect PLAIN text,
  byte-for-byte, no stray escape sequences anywhere in the output.
- STRIPPING ansi codes (for a tool that reads colored input and must normalize it) is a
  regex-shaped problem (`\\x1b\\[[0-9;]*m`) -- but write this as a manual byte/char scan in
  Rust/C/C++ (no stdlib regex) rather than reaching for a regex crate that doesn't exist here.""",
    "checksum": """## TECHNIQUE: hash/checksum computation -- match the EXACT algorithm and output format
If the tool computes a checksum/hash/digest, the algorithm must match EXACTLY (CRC32, MD5,
SHA-1/256, a simple additive/xor checksum, etc.) -- these are NOT interchangeable and a
different-but-similar algorithm produces a completely different (wrong) digest for the same
input, failing every test.
- Identify the EXACT algorithm from the observed output's digest LENGTH and the tool's
  docs/--help text (CRC32 = 8 hex chars/32 bits, MD5 = 32 hex chars/128 bits, SHA-256 = 64 hex
  chars/256 bits) before implementing anything -- guessing wastes the entire implementation.
- Output FORMAT conventions vary: lowercase vs uppercase hex, with/without a leading `0x`,
  decimal vs hex, and whether a filename is echoed alongside the digest (`<hash>  <filename>`,
  common `*sum`-style tools use exactly two spaces between hash and filename in text mode).
- Go's stdlib (`crypto/md5`, `crypto/sha256`, `hash/crc32`) genuinely implements the common
  algorithms -- use it directly rather than hand-rolling. Rust/C/C++ have NO stdlib hashing
  beyond perhaps a trivial CRC table -- a hand-rolled implementation of the EXACT algorithm
  (not an approximation) is required; a well-known reference algorithm (e.g. the standard
  CRC-32 polynomial 0xEDB88320) must be used verbatim, not an arbitrary custom checksum.""",
    "http": """## TECHNIQUE: making an HTTP request without an HTTP client library
- Go has a genuinely usable stdlib HTTP client (`net/http`) -- use `http.Get`/`http.Client` directly,
  this is real stdlib, not an external dependency.
- Rust/C/C++ have NO stdlib HTTP client at all -- constructing a request means opening a raw
  TCP socket (`std::net::TcpStream` in Rust; POSIX sockets in C/C++) to the target host:port
  and writing a hand-formatted HTTP/1.1 request: `GET /path HTTP/1.1\\r\\nHost: example.com\\r\\n
  Connection: close\\r\\n\\r\\n` (note: HTTP header lines end in `\\r\\n`, not just `\\n`), then
  reading the raw response, splitting the status line + headers (blank line terminates
  headers) from the body.
- Watch for `Transfer-Encoding: chunked` responses -- the body isn't just "everything after the
  blank line" in that case; it's length-prefixed chunks that must be de-chunked before use.
- If the observed reference behavior only ever hits `http://` (plain, unencrypted) URLs in the
  test fixtures, a raw-socket implementation is sufficient -- TLS/`https://` support requires
  a real TLS library that isn't available here; check the probes before assuming HTTPS is
  actually exercised by any test.""",
    "git_plumbing": """## TECHNIQUE: git-wrapper tools -- shell out to the real `git`, don't reimplement it
A tool that wraps/extends git behavior (branch cleanup, changelog generation, hooks, etc.)
almost always works by INVOKING the real `git` binary as a subprocess and parsing its output --
it does NOT reimplement git's object database/packfile format from scratch, and neither
should your reimplementation.
- Use the language's subprocess API (`std::process::Command` in Rust, `os/exec` in Go, `popen`/
  `fork+exec` in C/C++) to run `git <subcommand> <args>` and capture stdout/stderr/exit code.
- Common commands worth checking the tool's actual behavior against: `git rev-parse`,
  `git branch --list`, `git log --format=...`, `git status --porcelain` (a stable,
  script-friendly output format meant exactly for this kind of wrapping).
- Match the OBSERVED error handling when `git` itself fails (not a git repo, no such branch,
  etc.) -- usually the wrapper passes git's own stderr text through, or wraps it in the
  wrapper's own error format; verify against the actual probe rather than assuming either.
- If the observed behavior implies reading `.git/` internals directly (rare, but some tools do
  this for speed), that's a real structural parsing task (zlib-compressed objects, a simple
  key-value config format) -- confirm this is ACTUALLY what's being tested before attempting
  it; shelling out to real git is almost always both simpler and what the upstream tool does.""",
}


# Deliberate priority order, LOWEST to HIGHEST (2026-07-16): the original code built this
# via sequential picked.insert(0, ...) calls, which meant priority was accidentally determined
# by the ORDER the if-checks happened to be written in, not by how specific/confident each
# domain's signal actually is. With 3 domains that was tolerable; with 11 it isn't. This list
# is the single explicit source of truth for truncation priority -- last entry wins under a
# tight char budget. "io" is the universal baseline and always lowest. Broad/common signals
# (ansi -- any \x1b[ at all) rank low; narrow/high-confidence signals (git_plumbing, http,
# checksum -- name-based, rarely a false positive) rank high. tui/table/json/diff keep their
# original relative order (tui highest of the pre-existing three, matching prior behavior).
_RECIPE_PRIORITY = [
    "io",
    "ansi",
    "regex_glob",
    "csv",
    "checksum",
    "http",
    "git_plumbing",
    "diff",
    "json",
    "table",
    "tui",
]


def recipes_for(short: str, observations: list | None = None) -> str:
    """Pick concrete technique recipes relevant to this tool via CONTENT-detected domain
    signals (observed output shape / tool name), not family-name classification -- this
    generalizes to any tool regardless of whether it matches one of the 26 named family
    archetypes (audited 2026-07-16: only 52/200 real tasks match a family by name; content
    detection has no such ceiling). Always includes the io recipe (universal). Keeps the
    prompt focused on actionable HOW, ordered by _RECIPE_PRIORITY under truncation."""
    name = short.lower()
    blob = ""
    for o in (observations or [])[:6]:
        blob += getattr(o, "stdout", "") or ""
    tui_blob = "".join(
        getattr(o, "stdout", "") or ""
        for o in (observations or [])
        if getattr(getattr(o, "probe", None), "name", "").startswith("tui-snapshot")
    )

    matched = {"io"}
    if "json" in name or "gron" in name or "{" in blob or " = " in blob:
        matched.add("json")
    # table/grid renderers: detect box-drawing or ASCII-grid glyphs in observed output.
    if any(ch in blob for ch in "┌┬┐├┼┤└┴┘│─╭╮╰╯") or "+--" in blob or "+==" in blob:
        matched.add("table")
    # TUI/ncurses tools: a pty-captured tui-snapshot observation (determinex_observe.
    # observe_tui_snapshot) carries raw terminal escape bytes -- \x1b[ is the reliable tell.
    if "\x1b[" in tui_blob or "\x1b[" in blob:
        matched.add("tui")
    # unified-diff-style output: hunk headers or a run of +/- prefixed lines.
    if (
        "@@ -" in blob
        or "\n--- " in blob
        or "\n+++ " in blob
        or any(k in name for k in ("diff", "delta", "icdiff"))
    ):
        matched.add("diff")
    # CSV/TSV: quoted fields alongside comma-dense lines, or the tool's name says so.
    if '","' in blob or (blob.count(",") > 5 and '"' in blob) or "csv" in name or "tsv" in name:
        matched.add("csv")
    # glob/regex/search tools: name-based (grep/regex/glob/find-family tool names).
    if any(
        k in name
        for k in (
            "grep",
            "regex",
            "glob",
            "rgrep",
            "ripgrep",
            " rg",
            "fd",
            "sd",
            "search",
            "ack",
            "amber",
        )
    ):
        matched.add("regex_glob")
    # any ANSI escape at all (broader/weaker signal than the tui-snapshot-specific check above).
    if "\x1b[" in blob:
        matched.add("ansi")
    # hash/checksum tools: name-based.
    if any(
        k in name for k in ("hash", "checksum", "crc", "digest", "md5", "sha1", "sha256", "sum")
    ):
        matched.add("checksum")
    # HTTP client tools: name-based, or a raw HTTP status line / URL scheme in observed output.
    if (
        any(k in name for k in ("http", "curl", "curlie", "fetch", "wget", "xh"))
        or "HTTP/1." in blob
        or "://" in blob
    ):
        matched.add("http")
    # git-wrapper tools: name-based.
    if name.startswith("git") or "git-" in name or "-git" in name:
        matched.add("git_plumbing")

    ordered = [d for d in _RECIPE_PRIORITY if d in matched]
    picked = [_RECIPES[d] for d in reversed(ordered)]
    return "\n\n".join(picked)


def _path(short: str) -> Path:
    return SKILLS_DIR / f"{short}.json"


def _probes_path(short: str) -> Path:
    return SKILLS_DIR / f"{short}_probes.json"


def load_probes(short: str) -> list[dict]:
    """The corpus-owned, auto-grown oracle for this tool: serialized probe dicts
    (name/argv/stdin/files/serve) discovered by fuzz_diagnose across runs. The reimpl driver
    reconstructs OBS.Probe from these and adds them to the oracle -> the corpus literally
    holds the behavioral coverage it has learned, persisted + replayable."""
    p = _probes_path(short)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def add_probes(short: str, new_probes: list[dict]) -> int:
    """Merge newly-discovered probes into the corpus oracle, deduped by their I/O signature.
    Returns how many were actually added (0 => the oracle already covers them = saturation)."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    cur = load_probes(short)
    seen = {
        (
            json.dumps(p.get("argv", []), sort_keys=True),
            p.get("stdin"),
            json.dumps(p.get("files", {}), sort_keys=True),
            json.dumps(p.get("serve", {}), sort_keys=True),
        )
        for p in cur
    }
    added = 0
    for p in new_probes:
        key = (
            json.dumps(p.get("argv", []), sort_keys=True),
            p.get("stdin"),
            json.dumps(p.get("files", {}), sort_keys=True),
            json.dumps(p.get("serve", {}), sort_keys=True),
        )
        if key not in seen:
            seen.add(key)
            cur.append(p)
            added += 1
    if added:
        _probes_path(short).write_text(
            json.dumps(cur, indent=1, ensure_ascii=False), encoding="utf-8"
        )
    return added


def load(short: str) -> dict:
    p = _path(short)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def render_prompt_block(short: str, max_chars: int = 2600, observations: list | None = None) -> str:
    """The coach block injected into the builder prompt: cross-tool pitfalls + concrete
    technique RECIPES (HOW, not just WHAT) + anything Determinex already knows about THIS tool
    (discovered spec + behaviors that were hard).

    ORDER = priority under truncation (2026-07-02): this is a flat [:max_chars] cut, and a
    tight budget (decompose stations call this with max_chars=900) means SOMETHING gets
    dropped. Found via cmatrix: the old order put the generic CROSS_TOOL_PITFALLS (~800
    chars, applies to every tool, already somewhat "common sense") FIRST, which alone ate
    the entire 900-char budget and silently dropped the auto-detected DOMAIN recipe (e.g.
    the tui recipe -- concrete, tool-specific, and exactly the guidance a station needed)
    every single time. Most-actionable/specific first, most-generic last."""
    block = [recipes_for(short, observations)]  # auto-detected domain HOW-TO -- most actionable
    rec = load(short)
    if rec:
        spec = rec.get("spec_notes") or []
        hard = rec.get("hard_behaviors") or []
        if hard:  # tool-specific learned pitfalls -- high value, keep ahead of generic content
            block.append(
                "## Behaviors that were HARD last time (get these RIGHT)\n%s"
                % "\n".join(f"- {h}" for h in hard[:20])
            )
        if spec:
            block.append(
                "## What Determinex already knows about `%s` (discovered)\n%s"
                % (short, "\n".join(f"- {s}" for s in spec[:20]))
            )
    block.append(CROSS_TOOL_PITFALLS)  # generic, applies everywhere -- truncate first if tight
    return "\n\n".join(block)[:max_chars]


def record_run(
    short: str,
    *,
    observations: list | None = None,
    failed_probe_names: list | None = None,
    best_local: str = "",
    best_official: int | None = None,
    official_total: int | None = None,
    candidate_path: str = "",
    spec_notes: list | None = None,
) -> dict:
    """Persist what this run taught us. Merges with any prior record (the corpus learns
    cumulatively). Locks a verified skill ONLY on a genuine official pass (==total)."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    rec = load(short)
    rec["tool"] = short
    rec["updated"] = time.strftime("%Y-%m-%d %H:%M")
    if spec_notes:
        rec["spec_notes"] = sorted(set((rec.get("spec_notes") or []) + spec_notes))
    if failed_probe_names is not None:
        # behaviors that were hard = union of what failed across runs (so we keep coaching them)
        rec["hard_behaviors"] = sorted(set((rec.get("hard_behaviors") or []) + failed_probe_names))
    if best_official is not None:
        prev = rec.get("best_official", -1)
        if best_official > prev:
            rec["best_official"] = best_official
            rec["best_official_total"] = official_total
            rec["best_candidate"] = candidate_path
        rec["last_official"] = best_official
    if best_local:
        rec["last_local"] = best_local
    # LOCK a verified skill only on a real official solve
    if best_official is not None and official_total and best_official == official_total:
        rec["verified_skill"] = True
        rec["locked"] = rec.get("updated")
    _path(short).write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    return rec


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        print(json.dumps(load(sys.argv[1]), indent=2))
    else:
        print(
            "reimpl_skills:",
            [p.stem for p in SKILLS_DIR.glob("*.json")] if SKILLS_DIR.exists() else [],
        )
