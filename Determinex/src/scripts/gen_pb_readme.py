#!/usr/bin/env python3
"""Generate corpus/programbench/README.md — the one-stop ProgramBench master catalog.

Sources pulled:
  eval_index.json              → scores, tiers, eval paths, sub_buckets
  corpus/programbench/locked/  → locked dir existence, files within each dir
  corpus/programbench/per_tool_overrides/  → override dir existence + commit hash
  corpus/programbench/_strategy/_residual_table.md  → language per tool
  TOOL_META dict below        → short description + cluster siblings (curated)

Output: corpus/programbench/README.md
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).parent.parent
INDEX = REPO / "corpus/programbench/eval_index.json"
LOCKED = REPO / "corpus/programbench/locked"
OVERRIDES = REPO / "corpus/programbench/per_tool_overrides"
RESIDUAL = REPO / "corpus/programbench/_strategy/_residual_table.md"
KNOWLEDGE = REPO / "corpus/programbench/build_knowledge.json"
OUT = REPO / "corpus/programbench/README.md"

# ─────────────────────────────────────────────────────────────────
# Curated per-tool metadata: description, language, cluster siblings
# Keys are the canonical slug from eval_index.json
# ─────────────────────────────────────────────────────────────────
TOOL_META = {
    # ── T1 Strict Locks ──────────────────────────────────────────
    "jq": {
        "desc": "JSON processor — filters, transforms, queries JSON streams",
        "lang": "c",
        "cluster": ["yq", "xq", "dsq", "gron"],
    },
    "yq": {
        "desc": "YAML/JSON/TOML processor; jq-syntax queries for YAML",
        "lang": "go",
        "cluster": ["jq", "xq"],
    },
    "xq": {
        "desc": "XML/HTML query tool with jq-like syntax",
        "lang": "go",
        "cluster": ["jq", "yq"],
    },
    "gron": {
        "desc": "Flattens JSON to greppable lines; makes JSON greppable",
        "lang": "go",
        "cluster": ["jq"],
    },
    "dsq": {
        "desc": "SQL queries over CSV/JSON/Parquet files; multi-format join",
        "lang": "go",
        "cluster": ["jq", "trdsql"],
    },
    "trdsql": {
        "desc": "SQL queries over CSV/TSV/JSON/LTSV; supports MySQL/PG syntax",
        "lang": "go",
        "cluster": ["dsq"],
    },
    "angle-grinder": {
        "desc": "Log parsing & aggregation DSL; filter/group-by/sum on log lines",
        "lang": "rs",
        "cluster": ["rhit", "fblog"],
    },
    "ripgrep": {
        "desc": "Regex search across files; respects .gitignore; faster than grep",
        "lang": "rs",
        "cluster": ["shellharden", "diffr"],
    },
    "shellharden": {
        "desc": "Shell script linter/formatter; hardens quoting and variable handling",
        "lang": "rs",
        "cluster": ["ripgrep"],
    },
    "zoxide": {
        "desc": "Smarter cd; learns frecency-ranked directory jumps",
        "lang": "rs",
        "cluster": ["nomino", "rnr"],
    },
    "pastel": {
        "desc": "Color manipulation CLI — convert, mix, lighten/darken colors",
        "lang": "rs",
        "cluster": [],
    },
    "grex": {
        "desc": "Generates minimal regex patterns from user-provided examples",
        "lang": "rs",
        "cluster": [],
    },
    "hyperfine": {
        "desc": "Benchmarking tool — runs commands N times, stats on timing",
        "lang": "rs",
        "cluster": [],
    },
    "ripsecrets": {
        "desc": "Scans files/git history for hardcoded secrets and API keys",
        "lang": "rs",
        "cluster": [],
    },
    "cmatrix": {
        "desc": "Matrix-style falling-character terminal animation",
        "lang": "c",
        "cluster": ["genact"],
    },
    "genact": {
        "desc": "Fake activity simulator — makes terminal look busy",
        "lang": "rs",
        "cluster": ["cmatrix"],
    },
    "go-mod-outdated": {
        "desc": "Lists outdated Go module dependencies",
        "lang": "go",
        "cluster": [],
    },
    "gron": {
        "desc": "Flattens JSON to greppable discrete assignments",
        "lang": "go",
        "cluster": ["jq"],
    },
    "ascii-image-converter": {
        "desc": "Converts images to ASCII art in terminal",
        "lang": "go",
        "cluster": [],
    },
    "boyter__scc.515f91c": {
        "desc": "Code counter — lines of code/comments/blanks per language (scc)",
        "lang": "go",
        "cluster": [],
    },
    "stathissideris__ditaa": {
        "desc": "Converts ASCII art diagrams to PNG/SVG images",
        "lang": "java",
        "cluster": [],
    },
    "bore": {
        "desc": "TCP tunnel — exposes local ports through a remote server",
        "lang": "rs",
        "cluster": ["miniserve", "muffet"],
    },
    "miniserve": {
        "desc": "Minimal HTTP file server — serve a directory over HTTP",
        "lang": "rs",
        "cluster": ["bore", "muffet"],
    },
    "muffet": {
        "desc": "Fast website link checker; crawls for broken links",
        "lang": "go",
        "cluster": ["miniserve"],
    },
    "clog-cli": {
        "desc": "Changelog generator from conventional commit history",
        "lang": "rs",
        "cluster": ["git-trim"],
    },
    "code-minimap": {
        "desc": "Terminal minimap of source code scrollbar",
        "lang": "rs",
        "cluster": [],
    },
    "curlie": {
        "desc": "HTTP client combining curl flags with httpie-style output",
        "lang": "go",
        "cluster": ["muffet"],
    },
    "deadnix": {
        "desc": "Nix file analyzer; finds unused variables in Nix expressions",
        "lang": "rs",
        "cluster": [],
    },
    "diffr": {"desc": "Diff viewer with character-level highlighting", "lang": "rs", "cluster": []},
    "dupl": {"desc": "Source code duplicate detector across files", "lang": "go", "cluster": []},
    "entr": {
        "desc": "File watcher — re-runs commands when files change",
        "lang": "c",
        "cluster": [],
    },
    "eva": {
        "desc": "Calculator REPL with variable support and arbitrary precision",
        "lang": "rs",
        "cluster": [],
    },
    "fasttext": {
        "desc": "Facebook's text classification and word vector library",
        "lang": "c++",
        "cluster": [],
    },
    "fblog": {
        "desc": "JSON log viewer with color highlighting and field filtering",
        "lang": "rs",
        "cluster": ["angle-grinder", "rhit"],
    },
    "flamelens": {"desc": "Interactive flamegraph viewer in terminal", "lang": "rs", "cluster": []},
    "git-trim": {
        "desc": "Trims merged/stale git branches automatically",
        "lang": "rs",
        "cluster": ["clog-cli"],
    },
    "hck": {
        "desc": "Field-splitting like cut but with regex delimiters",
        "lang": "rs",
        "cluster": [],
    },
    "hex": {
        "desc": "Hex dump viewer with color and multiple display modes",
        "lang": "rs",
        "cluster": [],
    },
    "i3-style": {
        "desc": "Applies color themes to i3/Sway window manager configs",
        "lang": "rs",
        "cluster": [],
    },
    "ivanceras__svgbob": {
        "desc": "ASCII diagram-to-SVG converter",
        "lang": "rs",
        "cluster": ["stathissideris__ditaa"],
    },
    "loop": {
        "desc": "Runs commands in a loop with delay/count/until options",
        "lang": "rs",
        "cluster": ["entr"],
    },
    "ngrrram": {
        "desc": "Typing speed trainer for command-line users",
        "lang": "rs",
        "cluster": ["thokr"],
    },
    "nomino": {"desc": "Bulk file renamer with regex patterns", "lang": "rs", "cluster": ["rnr"]},
    "pier": {
        "desc": "Command alias manager — save and run frequently-used commands",
        "lang": "rs",
        "cluster": [],
    },
    "rhit": {
        "desc": "Apache/Nginx log analyzer with fast path stats",
        "lang": "rs",
        "cluster": ["angle-grinder", "fblog"],
    },
    "rnr": {
        "desc": "Recursive bulk file/directory renamer with regex support",
        "lang": "rs",
        "cluster": ["nomino"],
    },
    "rust-embedded__svd2rust.1760b5e": {
        "desc": "Converts CMSIS-SVD files to Rust peripheral access crate",
        "lang": "rs",
        "cluster": [],
    },
    "seqtk": {"desc": "Fast FASTQ/FASTA sequence processing toolkit", "lang": "c", "cluster": []},
    "tailspin": {
        "desc": "Log file highlighter — colorizes log levels, IPs, paths, dates",
        "lang": "rs",
        "cluster": ["fblog"],
    },
    "tex-fmt": {
        "desc": "LaTeX formatter — consistent indentation for TeX/LaTeX files",
        "lang": "rs",
        "cluster": [],
    },
    "thokr": {
        "desc": "Terminal typing test with WPM/accuracy stats",
        "lang": "rs",
        "cluster": ["ngrrram"],
    },
    "tparse": {
        "desc": "Formats and colorizes go test output with pass/fail/coverage stats",
        "lang": "go",
        "cluster": [],
    },
    "trasta298__keifu.3331426": {
        "desc": "TUI bookmark/note manager with sqlite backend",
        "lang": "rs",
        "cluster": [],
    },
    "xsv": {
        "desc": "Fast CSV toolkit — slice, select, join, search, stats on CSV",
        "lang": "rs",
        "cluster": ["dsq", "trdsql"],
    },
    "yj": {
        "desc": "Converts between YAML/TOML/JSON/HCL formats",
        "lang": "go",
        "cluster": ["yq", "xq"],
    },
    "chmln__handlr": {
        "desc": "XDG MIME handler replacement for xdg-open",
        "lang": "rs",
        "cluster": [],
    },
    "dsq": {
        "desc": "SQL queries over CSV/JSON/Parquet; multi-format join",
        "lang": "go",
        "cluster": ["jq", "trdsql"],
    },
    "flamelens": {"desc": "Interactive flamegraph viewer in terminal", "lang": "rs", "cluster": []},
    # ── T2 Ceiling Certified ────────────────────────────────────
    "htmlq": {
        "desc": "CSS selector queries on HTML — like jq but for HTML",
        "lang": "rs",
        "cluster": ["jq", "xq"],
    },
    "ripgrep": {
        "desc": "Regex search; respects .gitignore; fastest grep replacement",
        "lang": "rs",
        "cluster": ["shellharden"],
    },
    "quickjs": {
        "desc": "Lightweight embeddable JavaScript engine (Bellard)",
        "lang": "c",
        "cluster": [],
    },
    "csview": {
        "desc": "Pretty-print CSV files in terminal table format",
        "lang": "rs",
        "cluster": ["xsv"],
    },
    "chroma": {
        "desc": "Syntax highlighter library + CLI for 200+ languages",
        "lang": "go",
        "cluster": [],
    },
    "pingu": {
        "desc": "Ping replacement with pingu ASCII art animation",
        "lang": "rs",
        "cluster": [],
    },
    "zip-password-finder": {
        "desc": "Brute-force ZIP password cracker (wordlist/charset)",
        "lang": "rs",
        "cluster": [],
    },
    "sd": {
        "desc": "Find-and-replace CLI; simpler sed replacement",
        "lang": "rs",
        "cluster": ["nomino", "rnr"],
    },
    "tuc": {
        "desc": "Field cutter like cut with delimiter regex and ranges",
        "lang": "rs",
        "cluster": ["hck"],
    },
    "cheat__cheat": {
        "desc": "Cheatsheet manager — store/retrieve personal cheat sheets",
        "lang": "go",
        "cluster": [],
    },
    "blake3-team__blake3": {
        "desc": "BLAKE3 cryptographic hash function CLI (b3sum)",
        "lang": "rs",
        "cluster": [],
    },
    # ── T3 Open — near_miss ──────────────────────────────────────
    "elfcat": {
        "desc": "ELF binary viewer — parse and display ELF headers/sections",
        "lang": "rs",
        "cluster": [],
    },
    "junegunn__fzf.b56d614": {
        "desc": "General-purpose fuzzy finder for terminal (most widely used TUI)",
        "lang": "go",
        "cluster": ["peco", "skim"],
    },
    "argc": {
        "desc": "Bash argument parser generator — creates CLI from comments",
        "lang": "rs",
        "cluster": [],
    },
    "filosottile__age": {
        "desc": "Simple, modern file encryption (age format)",
        "lang": "go",
        "cluster": [],
    },
    "cslarsen__jp2a": {
        "desc": "Converts JPEG images to ASCII art",
        "lang": "c",
        "cluster": ["ascii-image-converter"],
    },
    "cmatsuoka__figlet": {
        "desc": "Large ASCII art text banners from fonts",
        "lang": "c",
        "cluster": [],
    },
    "incu6us__goimports-reviser": {
        "desc": "Go import sorter/grouper that enforces import sections",
        "lang": "go",
        "cluster": [],
    },
    "isona__dirble": {
        "desc": "Fast web directory brute-forcer / content discovery",
        "lang": "rs",
        "cluster": [],
    },
    "kisielk__errcheck": {
        "desc": "Go static analyzer that checks for unhandled errors",
        "lang": "go",
        "cluster": [],
    },
    "crowdagger__crowbook": {
        "desc": "Markdown-to-book converter (EPUB/HTML/PDF)",
        "lang": "rs",
        "cluster": [],
    },
    "direnv__direnv": {
        "desc": "Shell extension to load/unload env vars per directory",
        "lang": "go",
        "cluster": [],
    },
    "oha": {
        "desc": "HTTP load tester with real-time TUI stats dashboard",
        "lang": "rs",
        "cluster": ["muffet"],
    },
    "madler__pigz": {
        "desc": "Parallel gzip compressor — multi-threaded gzip replacement",
        "lang": "c",
        "cluster": [],
    },
    # ── T3 Open — rebaseline_needed ──────────────────────────────
    "go-critic__go-critic": {
        "desc": "Go linter with many opinionated checks beyond golint",
        "lang": "go",
        "cluster": [],
    },
    "pls-rs__pls": {
        "desc": "ls replacement with git-awareness and detailed file info",
        "lang": "rs",
        "cluster": [],
    },
    "mgechev__revive": {
        "desc": "Fast, extensible Go linter with configurable rules",
        "lang": "go",
        "cluster": [],
    },
    "nsh": {"desc": "Experimental shell with Lisp-inspired syntax", "lang": "rs", "cluster": []},
    "tarka__xcp": {
        "desc": "Extended cp with progress bar and parallel copies",
        "lang": "rs",
        "cluster": [],
    },
    "skeema__skeema": {
        "desc": "MySQL schema management via declarative files + git",
        "lang": "go",
        "cluster": [],
    },
    "rust-lang__mdbook": {
        "desc": "Markdown documentation book renderer (used by Rust Book)",
        "lang": "rs",
        "cluster": [],
    },
    "ducaale__xh": {
        "desc": "HTTPie-compatible HTTP client; curl replacement with friendly syntax",
        "lang": "rs",
        "cluster": ["curlie"],
    },
    "ninja-build__ninja": {
        "desc": "Small build system focused on speed (used by Chromium/LLVM)",
        "lang": "c++",
        "cluster": [],
    },
    "sharkdp__bat": {
        "desc": "Cat replacement with syntax highlighting and git diff integration",
        "lang": "rs",
        "cluster": ["diffr"],
    },
    "bootandy__dust": {
        "desc": "du replacement — disk usage tree with visual bars",
        "lang": "rs",
        "cluster": ["dua-cli"],
    },
    "xampprocky__tokei": {
        "desc": "Code statistics — count lines by language across a project",
        "lang": "rs",
        "cluster": ["boyter__scc.515f91c"],
    },
    "nachoparker__dutree": {
        "desc": "du output tree viewer with color and percentage bars",
        "lang": "rs",
        "cluster": ["bootandy__dust"],
    },
    "ov": {
        "desc": "Feature-rich pager — replacement for less/more with TUI",
        "lang": "go",
        "cluster": [],
    },
    "elkowar__pipr": {
        "desc": "TUI pipeline builder — compose shell pipes interactively",
        "lang": "rs",
        "cluster": [],
    },
    "blacknon__hwatch": {
        "desc": "watch replacement with diff highlighting and history",
        "lang": "rs",
        "cluster": [],
    },
    "antonmedv__walk": {
        "desc": "Terminal file browser — fast minimal TUI file navigator",
        "lang": "go",
        "cluster": [],
    },
    "xorg62__tty-clock": {"desc": "Digital/analog clock in terminal", "lang": "c", "cluster": []},
    "drew-alleman__datasurgeon": {
        "desc": "CLI data transformation tool for records/fields",
        "lang": "rs",
        "cluster": [],
    },
    "kyoheiu__felix": {
        "desc": "TUI file manager with vim-like keybindings",
        "lang": "rs",
        "cluster": [],
    },
    "ecumene__rust-sloth": {
        "desc": "Fake slow terminal output simulator (typewriter effect)",
        "lang": "rs",
        "cluster": ["genact"],
    },
    "oppiliappan__statix": {
        "desc": "Nix linter with fix suggestions",
        "lang": "rs",
        "cluster": ["deadnix"],
    },
    "yassinebridi__serpl": {
        "desc": "Interactive search-and-replace with regex, TUI preview",
        "lang": "rs",
        "cluster": ["sd"],
    },
    "canop__broot": {
        "desc": "Interactive directory tree navigator with fuzzy search",
        "lang": "rs",
        "cluster": ["antonmedv__walk"],
    },
    "rust-ethereum__ethabi": {
        "desc": "Ethereum ABI encoder/decoder CLI",
        "lang": "rs",
        "cluster": [],
    },
    "segmentio__chamber": {
        "desc": "AWS SSM Parameter Store CLI for secret management",
        "lang": "go",
        "cluster": [],
    },
    "mkj__dropbear": {
        "desc": "Lightweight SSH server and client (embedded-focused)",
        "lang": "c",
        "cluster": [],
    },
    "nukesor__pueue": {
        "desc": "Task queue manager for long-running shell commands",
        "lang": "rs",
        "cluster": [],
    },
    "osgeo__gdal": {
        "desc": "Geospatial data format library and translator (ogr2ogr, gdal_*)",
        "lang": "c++",
        "cluster": [],
    },
    "gabotechs__dep-tree": {
        "desc": "Dependency tree visualizer for code files (TUI)",
        "lang": "rs",
        "cluster": [],
    },
    "astaxie__bat": {
        "desc": "Go rewrite of cat with syntax highlighting (github.com/astaxie)",
        "lang": "go",
        "cluster": ["sharkdp__bat"],
    },
    "unhappychoice__gittype": {
        "desc": "Typing practice using real git diffs as training text",
        "lang": "rs",
        "cluster": ["ngrrram", "thokr"],
    },
    "jarun__nnn": {
        "desc": "Fast, feature-rich TUI file manager",
        "lang": "c",
        "cluster": ["kyoheiu__felix"],
    },
    "jesseduffield__lazygit": {
        "desc": "TUI git client — stage/commit/branch/diff visually",
        "lang": "go",
        "cluster": [],
    },
    "google__brotli": {
        "desc": "Brotli compression algorithm CLI encoder/decoder",
        "lang": "c",
        "cluster": ["madler__pigz"],
    },
    "eudoxia0__hashcards": {
        "desc": "CLI flashcard system using hash-based spaced repetition",
        "lang": "rs",
        "cluster": [],
    },
    "guumaster__hostctl": {
        "desc": "Hosts file manager — enable/disable groups of host entries",
        "lang": "go",
        "cluster": [],
    },
    "rochacbruno__marmite": {
        "desc": "Static site generator from Markdown files",
        "lang": "rs",
        "cluster": [],
    },
    "dandavison__delta": {
        "desc": "Diff pager with syntax highlighting (git-delta)",
        "lang": "rs",
        "cluster": ["diffr"],
    },
    "lfos__calcurse": {"desc": "TUI calendar and todo manager", "lang": "c", "cluster": []},
    "naggie__dstask": {
        "desc": "Git-based task manager with priorities and dependencies",
        "lang": "go",
        "cluster": [],
    },
    "peco__peco": {
        "desc": "Interactive line filter — predecessor to fzf",
        "lang": "go",
        "cluster": ["junegunn__fzf.b56d614"],
    },
    "o2sh__onefetch": {
        "desc": "Git repo summary in terminal with language stats and ASCII art",
        "lang": "rs",
        "cluster": [],
    },
    "tstack__lnav": {
        "desc": "Advanced log file navigator with SQL queries over logs",
        "lang": "c++",
        "cluster": ["angle-grinder", "fblog"],
    },
    "hush-shell__hush": {
        "desc": "Experimental statically-typed shell language",
        "lang": "rs",
        "cluster": [],
    },
    "lua__lua": {"desc": "Lua 5.4 interpreter and REPL", "lang": "c", "cluster": []},
    "dundee__gdu": {
        "desc": "Fast disk usage analyzer with TUI",
        "lang": "go",
        "cluster": ["bootandy__dust", "nachoparker__dutree"],
    },
    "ip7z__7zip": {
        "desc": "7-Zip archiver CLI (7za/7zz) — compress, extract archives",
        "lang": "c++",
        "cluster": [],
    },
    "zk-org__zk": {
        "desc": "Zettelkasten note-taking CLI with search and linking",
        "lang": "go",
        "cluster": [],
    },
    "arq5x__bedtools2": {
        "desc": "Genome arithmetic CLI — intersect, merge, sort BED/VCF/BAM",
        "lang": "c++",
        "cluster": [],
    },
    "jonas__tig": {
        "desc": "TUI git browser — explore history, diffs, branches interactively",
        "lang": "c",
        "cluster": ["jesseduffield__lazygit"],
    },
    "tinycc__tinycc": {
        "desc": "Tiny C Compiler — fast compilation of C to native code",
        "lang": "c",
        "cluster": [],
    },
    "ammarabouzor__tui-journal": {
        "desc": "TUI journaling app with SQLite and markdown",
        "lang": "rs",
        "cluster": ["trasta298__keifu.3331426"],
    },
    "yoav-lavi__melody": {
        "desc": "Language for writing reusable shell commands (snippets + args)",
        "lang": "rs",
        "cluster": ["pier"],
    },
    "stacked-git__stgit": {
        "desc": "Stacked git — quilt-like patch management on top of git",
        "lang": "rs",
        "cluster": [],
    },
    "samtools__samtools": {
        "desc": "Suite for manipulating SAM/BAM genomics alignment files",
        "lang": "c",
        "cluster": ["arq5x__bedtools2"],
    },
    "run": {"desc": "Makefile-like task runner from run.toml files", "lang": "rs", "cluster": []},
    "ogham__dog": {
        "desc": "dig replacement — DNS lookup with colors and JSON output",
        "lang": "rs",
        "cluster": [],
    },
    "chirlu__sox": {
        "desc": "Sound eXchange — audio format converter and effects processor",
        "lang": "c",
        "cluster": [],
    },
    "gromacs__gromacs": {
        "desc": "Molecular dynamics simulation package (gmx CLI)",
        "lang": "c++",
        "cluster": [],
    },
    "tree-sitter__tree-sitter": {
        "desc": "Incremental parsing library CLI — parse files with grammars",
        "lang": "c",
        "cluster": [],
    },
    "alexpovel__srgn": {
        "desc": "Scoped regex replacer — transform only inside code regions",
        "lang": "rs",
        "cluster": ["sd"],
    },
    "epistates__treemd": {
        "desc": "Markdown tree visualizer — renders directory trees from markdown",
        "lang": "go",
        "cluster": [],
    },
    "facebook__zstd": {
        "desc": "Zstandard compression algorithm CLI encoder/decoder",
        "lang": "c",
        "cluster": ["google__brotli", "madler__pigz"],
    },
    "typst__typst": {
        "desc": "Modern document typesetting language + compiler (LaTeX alternative)",
        "lang": "rs",
        "cluster": ["tex-fmt"],
    },
    "paradigmxyz__solar": {
        "desc": "Solidity language server and compiler tools",
        "lang": "rs",
        "cluster": [],
    },
    "antonmedv__fx": {
        "desc": "Terminal JSON viewer/processor with interactive TUI",
        "lang": "go",
        "cluster": ["jq"],
    },
    "danmar__cppcheck": {
        "desc": "Static analysis tool for C/C++ code",
        "lang": "c++",
        "cluster": [],
    },
    "lz4__lz4": {
        "desc": "LZ4 compression algorithm CLI — fastest lossless compression",
        "lang": "c",
        "cluster": ["google__brotli", "facebook__zstd"],
    },
    "robertdavidgraham__masscan": {
        "desc": "Mass IP port scanner — internet-scale port scanning",
        "lang": "c",
        "cluster": [],
    },
    "universal-ctags__ctags": {
        "desc": "Universal ctags — source code tag generator for editors",
        "lang": "c",
        "cluster": [],
    },
    "hairyhenderson__gomplate": {
        "desc": "Template renderer using Go templates; substitutes env vars/data",
        "lang": "go",
        "cluster": [],
    },
    "stranger6667__jsonschema": {"desc": "JSON Schema validator CLI", "lang": "rs", "cluster": []},
    "luajit__luajit": {
        "desc": "LuaJIT — JIT-compiled Lua interpreter",
        "lang": "c",
        "cluster": ["lua__lua"],
    },
    "ffmpeg__ffmpeg": {
        "desc": "FFmpeg — video/audio converter, encoder, decoder, streamer",
        "lang": "c",
        "cluster": ["chirlu__sox"],
    },
    "parcel-bundler__lightningcss": {
        "desc": "CSS parser, transformer, minifier written in Rust",
        "lang": "rs",
        "cluster": [],
    },
    "jhspetersson__fselect": {
        "desc": "SQL-like file search queries (SELECT name FROM /path WHERE size > 1M)",
        "lang": "rs",
        "cluster": ["jq"],
    },
    "jgm__pandoc": {
        "desc": "Universal document converter (Markdown/HTML/DOCX/PDF/etc)",
        "lang": "haskell",
        "cluster": [],
    },
    "duckdb__duckdb": {
        "desc": "In-process analytical SQL database (DuckDB CLI)",
        "lang": "c++",
        "cluster": ["dsq", "trdsql"],
    },
    "osgeo__proj": {
        "desc": "PROJ cartographic projections and coordinate transformations",
        "lang": "c++",
        "cluster": [],
    },
    "sqlite__sqlite": {
        "desc": "SQLite database engine CLI (sqlite3)",
        "lang": "c",
        "cluster": ["duckdb__duckdb"],
    },
    "php__php-src": {"desc": "PHP interpreter CLI", "lang": "c", "cluster": []},
    "johnkerl__miller": {
        "desc": "Record-by-record processor for CSV/JSON/TSV — awk for structured data",
        "lang": "c",
        "cluster": ["jq", "dsq"],
    },
    "ast-grep__ast-grep": {
        "desc": "AST-based code search and rewrite tool",
        "lang": "rs",
        "cluster": [],
    },
    "byron__dua-cli": {
        "desc": "Disk Usage Analyzer TUI — fast du with interactive browser",
        "lang": "rs",
        "cluster": ["bootandy__dust", "dundee__gdu"],
    },
    "tomarrell__wrapcheck": {
        "desc": "Go linter that checks errors are wrapped on return",
        "lang": "go",
        "cluster": ["kisielk__errcheck"],
    },
    "hpjansson__chafa.dd4d4c1": {
        "desc": "Terminal graphics — renders images/video as colored unicode/braille",
        "lang": "c",
        "cluster": ["ascii-image-converter", "cslarsen__jp2a"],
    },
    "htop-dev__htop": {
        "desc": "Interactive process viewer TUI — top replacement",
        "lang": "c",
        "cluster": [],
    },
    "nikoladucak__caps-log": {
        "desc": "TUI journaling tool with calendar view and markdown",
        "lang": "rs",
        "cluster": ["ammarabouzor__tui-journal"],
    },
    "zevv__duc": {
        "desc": "Disk Usage Commander — indexing and TUI/CGI disk browser",
        "lang": "c",
        "cluster": ["dundee__gdu"],
    },
    # ── T3 Open — impossible_ceiling ─────────────────────────────
    "igrep": {
        "desc": "Searches regex in files; opens matches in vim/nvim (TUI)",
        "lang": "rs",
        "cluster": ["ripgrep"],
    },
    "parqeye": {
        "desc": "Parquet file viewer — display schema and rows from .parquet files",
        "lang": "go",
        "cluster": ["dsq"],
    },
    "rumdl": {
        "desc": "Markdown linter — checks Markdown style rules",
        "lang": "rs",
        "cluster": ["tex-fmt"],
    },
    "doxygen__doxygen": {
        "desc": "Documentation generator from annotated C/C++/Python/Java source",
        "lang": "c++",
        "cluster": [],
    },
    "orf__gping": {
        "desc": "Ping replacement with real-time TUI graph of latency",
        "lang": "rs",
        "cluster": [],
    },
    "kyoh86__richgo": {
        "desc": "go test output colorizer with rich formatting",
        "lang": "go",
        "cluster": ["tparse"],
    },
    "dalance__amber": {
        "desc": "Code search-and-replace with preview and regex",
        "lang": "rs",
        "cluster": ["sd"],
    },
    "johanneskaufmann__html-to-markdown": {
        "desc": "HTML-to-Markdown converter",
        "lang": "go",
        "cluster": [],
    },
    "sharkdp__fd": {
        "desc": "find replacement — simpler syntax, faster, respects .gitignore",
        "lang": "rs",
        "cluster": ["ripgrep"],
    },
    "sharkdp__hexyl": {
        "desc": "Hex viewer with colorized output and multiple displays",
        "lang": "rs",
        "cluster": ["hex"],
    },
    "sayanarijit__xplr": {
        "desc": "Hackable TUI file explorer with Lua scripting",
        "lang": "rs",
        "cluster": ["antonmedv__walk", "kyoheiu__felix"],
    },
    "nikolassv__bartib": {
        "desc": "TUI time tracker with start/stop/list commands",
        "lang": "rs",
        "cluster": [],
    },
    "json-tui": {
        "desc": "Interactive TUI JSON viewer with tree navigation",
        "lang": "rs",
        "cluster": ["jq", "antonmedv__fx"],
    },
    "eureka": {
        "desc": "TUI note-taking app for capturing ideas quickly",
        "lang": "rs",
        "cluster": [],
    },
    "xz": {
        "desc": "XZ/LZMA compression algorithm CLI",
        "lang": "c",
        "cluster": ["facebook__zstd", "google__brotli"],
    },
    "rustowl": {
        "desc": "Rust code ownership/lifetime visualizer in terminal",
        "lang": "rs",
        "cluster": [],
    },
    "axodotdev__oranda": {
        "desc": "Static site generator for project announcements/releases",
        "lang": "rs",
        "cluster": [],
    },
    # ── T3 Open — behavioral_deep ────────────────────────────────
    "monolith": {
        "desc": "Save web pages as self-contained HTML archives",
        "lang": "rs",
        "cluster": [],
    },
    "ggreer__the_silver_searcher": {
        "desc": "Ag — code search tool faster than ack",
        "lang": "c",
        "cluster": ["ripgrep"],
    },
    "ksxgithub__parallel-disk-usage": {
        "desc": "pdu — parallel du with TUI progress and tree output",
        "lang": "rs",
        "cluster": ["bootandy__dust"],
    },
    "shashwatah__jot": {
        "desc": "Note-taking CLI with color, tags, and fuzzy search",
        "lang": "go",
        "cluster": [],
    },
    "halitechallenge__halite": {
        "desc": "Halite strategy game bot framework and CLI",
        "lang": "c++",
        "cluster": [],
    },
    "hooklift__gowsdl": {
        "desc": "WSDL-to-Go code generator for SOAP web services",
        "lang": "go",
        "cluster": [],
    },
    "eliukblau__pixterm": {
        "desc": "Renders images as colored ASCII art in terminal",
        "lang": "go",
        "cluster": ["ascii-image-converter", "hpjansson__chafa.dd4d4c1"],
    },
    "quinn-rs__quinn": {
        "desc": "QUIC network protocol implementation CLI and library",
        "lang": "rs",
        "cluster": [],
    },
    "lymphatus__caesium-clt": {"desc": "Lossy image compressor CLI", "lang": "c++", "cluster": []},
    "cweill__gotests": {
        "desc": "Generates Go test boilerplate from function signatures",
        "lang": "go",
        "cluster": [],
    },
    "codesnap-rs__codesnap": {
        "desc": "Takes code snapshots with syntax highlighting (like carbon.sh)",
        "lang": "rs",
        "cluster": [],
    },
    "git-bahn__git-graph": {
        "desc": "Visualizes git branch graph in terminal",
        "lang": "rs",
        "cluster": ["jesseduffield__lazygit"],
    },
    "ariga__atlas": {
        "desc": "Database schema management and migration tool (Ent/SQL)",
        "lang": "go",
        "cluster": [],
    },
    "rhysd__kiro-editor": {
        "desc": "Terminal text editor in the vein of kilo",
        "lang": "go",
        "cluster": [],
    },
    "rs__jplot.2a54bcc": {
        "desc": "Real-time terminal plot of stdin data streams",
        "lang": "go",
        "cluster": [],
    },
    # ── T3 Open — tui_wall ───────────────────────────────────────
    "pls-rs__pls": {
        "desc": "ls replacement with git-awareness and detailed file info",
        "lang": "rs",
        "cluster": [],
    },
    "gabotechs__dep-tree": {
        "desc": "Dependency tree visualizer (TUI) for source files",
        "lang": "rs",
        "cluster": [],
    },
    "canop__broot": {
        "desc": "Interactive directory tree navigator with fuzzy search",
        "lang": "rs",
        "cluster": ["antonmedv__walk"],
    },
    "byron__dua-cli": {
        "desc": "Disk Usage Analyzer TUI — fast du with interactive browser",
        "lang": "rs",
        "cluster": ["bootandy__dust"],
    },
    "hpjansson__chafa.dd4d4c1": {
        "desc": "Terminal graphics with tmux support (chafa)",
        "lang": "c",
        "cluster": [],
    },
    "sayanarijit__xplr": {"desc": "Hackable TUI file explorer", "lang": "rs", "cluster": []},
    "jesseduffield__lazygit": {"desc": "TUI git client", "lang": "go", "cluster": []},
}


# Lang override map from residual_table (author/repo → lang)
def load_residual_langs() -> dict[str, str]:
    lang_map: dict[str, str] = {}
    try:
        text = RESIDUAL.read_text(encoding="utf-8")
        for line in text.splitlines():
            m = re.match(r"\|\s*\d+\s*\|\s*`([^/]+)/([^|`]+)`\s*\|\s*([a-z+]+)\s*\|", line)
            if m:
                owner = m.group(1).strip().lower()
                repo = m.group(2).strip().lower()
                lang = m.group(3).strip()
                lang_map[f"{owner}/{repo}"] = lang
    except FileNotFoundError:
        pass
    return lang_map


def slug_to_github_key(slug: str) -> str:
    """Convert eval_index slug like 'junegunn__fzf.b56d614' → 'junegunn/fzf'."""
    # Remove commithash suffix
    base = re.sub(r"\.[0-9a-f]{7,8}$", "", slug)
    # Double underscore → slash
    parts = base.split("__", 1)
    if len(parts) == 2:
        return f"{parts[0].lower()}/{parts[1].lower()}"
    return slug.lower()


def get_lang(slug: str, residual_langs: dict) -> str:
    meta = TOOL_META.get(slug, {})
    if meta.get("lang"):
        return meta["lang"]
    key = slug_to_github_key(slug)
    return residual_langs.get(key, "?")


def get_desc(slug: str) -> str:
    meta = TOOL_META.get(slug, {})
    return meta.get("desc", "—")


def get_cluster(slug: str) -> list[str]:
    meta = TOOL_META.get(slug, {})
    return meta.get("cluster", [])


def is_alias(e: dict) -> bool:
    if e.get("alias_of"):
        return True
    if e.get("tier") in ("tier_1_perfect", "tier_5_ceiling_confirmed"):
        return True
    if e.get("slug", "").endswith(".eval"):
        return True
    return False


def effective_failed(e: dict) -> int:
    f = e.get("official_failed", 0) or 0
    p = e.get("official_passed", 0) or 0
    t = e.get("official_total", 0) or 0
    nr = e.get("official_not_run", 0) or 0
    sk = e.get("official_skipped", 0) or 0
    return max(f, max(0, t - p - nr - sk))


def canonical_tier(e: dict) -> str:
    t = e.get("tier", "")
    if t in ("strict_lock", "ceiling_certified", "open"):
        return t
    if t == "tier_1_perfect":
        return "strict_lock"
    return "open"


# ── File discovery helpers ─────────────────────────────────────────────────


def find_locked_dir(slug: str) -> Path | None:
    """Return the locked/ subdirectory for this slug, or None."""
    # Try exact match
    exact = LOCKED / slug
    if exact.is_dir():
        return exact
    # Try prefix match (slug without commithash)
    base = re.sub(r"\.[0-9a-f]{7,8}$", "", slug)
    for d in LOCKED.iterdir():
        if d.is_dir() and (d.name == base or d.name.startswith(base)):
            return d
    return None


def locked_files(slug: str) -> dict[str, bool]:
    d = find_locked_dir(slug)
    if not d:
        return {}
    return {f.name: True for f in d.iterdir()}


def find_override_dir(slug: str) -> Path | None:
    """Return per_tool_overrides/ dir for this slug, or None."""
    # The override dirs use author__repo.commithash format
    # slug may already be in that format, or may be a short name
    for d in OVERRIDES.iterdir():
        if not d.is_dir() or d.name == ".vscode":
            continue
        base = re.sub(r"\.[0-9a-f]{7,8}$", "", d.name)
        slug_base = re.sub(r"\.[0-9a-f]{7,8}$", "", slug)
        if d.name == slug or base == slug_base or d.name.startswith(slug_base + "."):
            return d
    return None


def override_commit(slug: str) -> str:
    """Extract commit hash from override dir name."""
    d = find_override_dir(slug)
    if not d:
        return ""
    m = re.search(r"\.([0-9a-f]{7,8})$", d.name)
    return m.group(1) if m else ""


def eval_report_display(e: dict) -> str:
    p = e.get("eval_report_path", "") or ""
    if not p:
        return "—"
    # Shorten to relative path
    try:
        rel = Path(p)
        # If absolute, make relative to REPO
        if rel.is_absolute():
            rel = rel.relative_to(REPO)
        return str(rel).replace("\\", "/")
    except Exception:
        return p.replace("\\", "/")


def submission_path(slug: str) -> str:
    d = find_locked_dir(slug)
    if d and (d / "submission.tar.gz").exists():
        try:
            return str((d / "submission.tar.gz").relative_to(REPO)).replace("\\", "/")
        except Exception:
            return str(d / "submission.tar.gz")
    # Check per_tool_overrides
    od = find_override_dir(slug)
    if od:
        # submission.tar.gz might be in a subdirectory of per_tool_overrides
        pass
    return "—"


# ── Row builders ──────────────────────────────────────────────────────────


def phantom_guard(e: dict) -> str:
    """Return ⚠ PHANTOM if score looks 100% but Section 5 is unresolved.

    A row is phantom-guarded when:
      - display score == 100% (official_score_pct >= 100 OR passed==total), AND
      - official_full_suite_resolved is False, OR status is submetric_claim, OR
        any recorded note mentions 'Section 5 FAIL'.
    This prevents a clean-looking number from masquerading as a lock.
    """
    p = e.get("official_passed", 0) or 0
    t = e.get("official_total", 0) or 0
    full = e.get("official_full_suite_resolved", False)
    status = e.get("status", "") or ""
    tier = canonical_tier(e)

    # Only flag non-locked tools
    if tier in ("strict_lock", "ceiling_certified"):
        return ""

    # Check if display score is 100%
    display_100 = (t > 0 and p == t) or (e.get("official_score_pct", 0) or 0) >= 100.0

    if not display_100:
        return ""

    # Score looks 100% — check for Section 5 evidence of failure
    if status == "submetric_claim":
        return " ⚠PHANTOM(submetric)"
    if not full:
        # Check notes for Section 5 FAIL language
        for field in ("hetzner_eval_2026_06_11", "reconcile_note", "factory_note", "notes"):
            val = e.get(field, "") or ""
            if "Section 5 FAIL" in val or "section 5 fail" in val.lower():
                return " ⚠PHANTOM(Sec5-FAIL)"
        return " ⚠PHANTOM(unresolved)"
    return ""


def score_str(e: dict) -> str:
    p = e.get("official_passed", "?")
    t = e.get("official_total", "?")
    if p == "?" or t == "?":
        return "?/?"
    pct = f"{100 * p / t:.1f}" if t else "?"
    guard = phantom_guard(e)
    return f"{p}/{t} ({pct}%){guard}"


def detail_str(e: dict) -> str:
    f = effective_failed(e)
    nr = e.get("official_not_run", 0) or 0
    sk = e.get("official_skipped", 0) or 0
    parts = []
    if f:
        parts.append(f"f={f}")
    if nr:
        parts.append(f"nr={nr}")
    if sk:
        parts.append(f"sk={sk}")
    return " ".join(parts) or "—"


def next_action_str(e: dict) -> str:
    t = canonical_tier(e)
    f = effective_failed(e)
    nr = e.get("official_not_run", 0) or 0
    sk = e.get("official_skipped", 0) or 0
    sub = e.get("sub_bucket", "") or ""
    total = e.get("official_total", 0) or 0
    full = e.get("official_full_suite_resolved", False)

    if t == "strict_lock":
        return "✓ T1 locked"
    if t == "ceiling_certified":
        return "✓ T2 cert'd"
    if sub == "impossible_ceiling" or e.get("ceiling_confirmed"):
        return "⛔ impossible ceiling"
    if f == 0 and nr == 0 and sk > 0:
        return f"Write CEILING_CERT ({sk} sk) → T2"
    if f == 0 and nr == 0 and sk == 0 and not full:
        return "Verify → archive → T1"
    if nr == 0 and f > 0:
        pct = 100 * f / total if total else 0
        if f <= 3:
            return f"Fix {f} fail → T1"
        if f <= 10:
            return f"Fix {f} fail ({pct:.1f}%) → T1"
        if f <= 30:
            return f"Fix {f} fail ({pct:.1f}%) → near-lock"
        return f"Fix {f} fail ({pct:.1f}%) — large effort"
    if nr > 0:
        if sub == "tui_wall":
            return f"Add tmux ({nr} nr)"
        return f"Remove cap + eval ({nr} nr)"
    if sub == "tui_wall":
        return "Add tmux support"
    if sub == "behavioral_deep":
        return "Behavioral deep-dive"
    return f"Investigate (f={f} nr={nr} sk={sk})"


# ── Section builders ──────────────────────────────────────────────────────


def section_t1(tools: list[dict], residual_langs: dict) -> list[str]:
    lines = [
        "## T1 Strict Locks (passed == total, 0 fail, 0 nr, 0 sk)",
        "",
        "| Slug | Description | Lang | Tests | Tarball | Eval Report | Override | Lessons | Cluster siblings |",
        "|------|-------------|------|-------|---------|-------------|----------|---------|------------------|",
    ]
    for e in tools:
        slug = e["slug"]
        lfiles = locked_files(slug)
        has_lessons = "Y" if "lessons.md" in lfiles else "—"
        has_tar = "Y" if "submission.tar.gz" in lfiles else "—"
        eval_rpt = eval_report_display(e)
        od = find_override_dir(slug)
        override_str = f"`{od.name}`" if od else "—"
        lang = get_lang(slug, residual_langs)
        desc = get_desc(slug)
        cluster = ", ".join(f"`{s}`" for s in get_cluster(slug)) or "—"
        score = score_str(e)
        lines.append(
            f"| `{slug}` | {desc} | {lang} | {score} | {has_tar} | `{eval_rpt}` | {override_str} | {has_lessons} | {cluster} |"
        )
    lines.append("")
    return lines


def section_t2(tools: list[dict], residual_langs: dict) -> list[str]:
    lines = [
        "## T2 Ceiling Certified (f=0, nr=0, sk>0, CEILING_CERT.md present)",
        "",
        "| Slug | Description | Lang | Score | sk | CEILING_CERT | Override | Cluster |",
        "|------|-------------|------|-------|----|--------------|----------|---------|",
    ]
    for e in tools:
        slug = e["slug"]
        sk = e.get("official_skipped", 0) or 0
        lfiles = locked_files(slug)
        has_cert = "Y" if "CEILING_CERT.md" in lfiles else "—"
        eval_rpt = eval_report_display(e)
        od = find_override_dir(slug)
        override_str = f"`{od.name}`" if od else "—"
        lang = get_lang(slug, residual_langs)
        desc = get_desc(slug)
        cluster = ", ".join(f"`{s}`" for s in get_cluster(slug)) or "—"
        score = score_str(e)
        lines.append(
            f"| `{slug}` | {desc} | {lang} | {score} | {sk} | {has_cert} | {override_str} | {cluster} |"
        )
    lines.append("")
    return lines


def section_t3(tools: list[dict], residual_langs: dict) -> list[str]:
    from collections import defaultdict

    groups: dict[str, list[dict]] = defaultdict(list)
    for e in tools:
        sub = e.get("sub_bucket", "unknown") or "unknown"
        groups[sub].append(e)

    bucket_order = [
        "near_miss",
        "tui_wall",
        "behavioral_deep",
        "impossible_ceiling",
        "rebaseline_needed",
        "unknown",
    ]
    bucket_labels = {
        "near_miss": "### T3 near_miss — close to T1/T2, specific fix needed",
        "tui_wall": "### T3 tui_wall — blocked on TUI/tmux test execution",
        "behavioral_deep": "### T3 behavioral_deep — complex behavioral failures, large gap",
        "impossible_ceiling": "### T3 impossible_ceiling — proven structural ceiling < 100%",
        "rebaseline_needed": "### T3 rebaseline_needed — stale/low score; needs cap removal + fresh eval",
        "unknown": "### T3 unclassified",
    }

    lines = ["## T3 Open (135 tools — needs work)", ""]

    for bucket in bucket_order:
        tools_in = groups.get(bucket, [])
        if not tools_in:
            continue
        lines.append(bucket_labels.get(bucket, f"### T3 {bucket}"))
        lines.append("")
        lines.append(
            "| Slug | Description | Lang | Score | f/nr/sk | Override | Eval report | Next action | Ceiling/notes |"
        )
        lines.append(
            "|------|-------------|------|-------|---------|----------|-------------|-------------|---------------|"
        )

        # Sort by ascending failure count
        def sort_key(x: dict) -> tuple:
            return (effective_failed(x), x.get("official_not_run", 0) or 0)

        for e in sorted(tools_in, key=sort_key):
            slug = e["slug"]
            lang = get_lang(slug, residual_langs)
            desc = get_desc(slug)
            score = score_str(e)
            detail = detail_str(e)
            od = find_override_dir(slug)
            override_str = f"`{od.name}`" if od else "—"
            eval_rpt = eval_report_display(e)
            action = next_action_str(e)
            ceiling = (
                e.get("ceiling_note") or e.get("ceiling_reason") or e.get("hetzner_eval_note") or ""
            )[:80]
            if ceiling:
                ceiling = ceiling.replace("|", "/").replace("\n", " ")
            lines.append(
                f"| `{slug}` | {desc} | {lang} | {score} | {detail} | {override_str} | `{eval_rpt}` | {action} | {ceiling} |"
            )
        lines.append("")
    return lines


def section_roadmap() -> list[str]:
    """Render build_knowledge.roadmap_to_envisioned -- the corpus's own answer to
    'what else is needed to make all of this work'. Single-sourced from build_knowledge.json
    so the human board stays current with the RAG-retrievable knowledge."""
    try:
        rm = json.loads(KNOWLEDGE.read_text(encoding="utf-8")).get("roadmap_to_envisioned", {})
    except Exception:
        return []
    if not isinstance(rm, dict) or not rm:
        return []
    lines = [
        "## What's Needed to Reach the Vision",
        "",
        "> Set Determinex any code/idea → it is taken in, gated, fixed, and proven. This ledger is",
        "> generated from `build_knowledge.json:roadmap_to_envisioned` (RAG-retrievable — the system's",
        "> own answer to *what next + how*). Edit it there, not here.",
        "",
    ]
    sections = [
        ("self_healing", "Self-healing (automatable DETECT→FIX)"),
        ("remaining_work", "Remaining PB work"),
        ("system_wide_remaining", "System-wide (the whole product)"),
    ]
    for key, title in sections:
        block = rm.get(key, {})
        if not isinstance(block, dict) or not block:
            continue
        lines += [f"### {title}", ""]
        for k, v in block.items():
            if k == "_doc" or not isinstance(v, str):
                continue
            lines.append(f"- **{k}** — {v}")
        lines.append("")
    how = rm.get("how_to_ask")
    if isinstance(how, str):
        lines += [f"*How to ask the system: {how}*", ""]
    return lines


# ── Main document assembler ────────────────────────────────────────────────


def build_readme(data: list[dict], residual_langs: dict) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    canonical = [e for e in data if not is_alias(e)]
    t1 = sorted(
        [e for e in canonical if canonical_tier(e) == "strict_lock"],
        key=lambda e: e.get("slug", ""),
    )
    t2 = sorted(
        [e for e in canonical if canonical_tier(e) == "ceiling_certified"],
        key=lambda e: e.get("slug", ""),
    )
    t3 = [e for e in canonical if canonical_tier(e) == "open"]

    total_tests_t1 = sum(e.get("official_total", 0) or 0 for e in t1)
    total_tests = sum(e.get("official_total", 0) or 0 for e in canonical if e.get("official_total"))

    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────
    lines += [
        "---",
        "name: programbench-master-catalog",
        "description: One-stop reference for all 200 ProgramBench tools — scores, tiers, paths, descriptions, cluster siblings, ceilings.",
        "generated: auto — run `python3 scripts/gen_pb_readme.py` to refresh",
        f"last_updated: {now}",
        "---",
        "",
        "# ProgramBench Master Catalog",
        "",
        f"> **Generated:** {now[:10]}  ",
        "> **Source of truth:** `corpus/programbench/eval_index.json`  ",
        "> **Do not edit by hand** — run `python3 scripts/gen_pb_readme.py` to regenerate.",
        "",
        "## Quick Stats",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| **T1 strict locks** | **{len(t1)} / 200** ({100 * len(t1) / 200:.1f}%) |",
        f"| **T2 ceiling certified** | **{len(t2)}** |",
        f"| T3 open (needs work) | {len(t3)} |",
        f"| Total tests covered (T1 only) | {total_tests_t1:,} |",
        f"| Total tests in catalog | {total_tests:,} |",
        f"| Aliases / duplicates (not counted) | {len([e for e in data if is_alias(e)])} |",
        "",
        "## Key Files & Paths",
        "",
        "| What | Where |",
        "|------|-------|",
        "| Eval index (machine source of truth) | `corpus/programbench/eval_index.json` |",
        "| Tier table (auto-generated) | `corpus/programbench/GROUND_TRUTH.md` |",
        "| Priority action queue | `docs/programs/programbench/PB_PRIORITY_QUEUE.md` |",
        "| Per-tool locked archives | `corpus/programbench/locked/<tool>/` |",
        "| Per-tool compile.sh overrides | `corpus/programbench/per_tool_overrides/<author__repo.hash>/` |",
        "| Training corpus (verdict jsonl) | `corpus/programbench/training_corpus/pb_verdict_corpus.jsonl` |",
        "| Fix queue | `logs/programbench_factory/NATIVE_REJECT_FIX_QUEUE.md` |",
        "| Eval command | `cd T:/Dev/ProgramBench && PYTHONUTF8=1 uv run programbench eval <pilot_dir> --force` |",
        "",
        "## Lock Definition (mandatory)",
        "",
        "- **T1 strict_lock**: `passed == total`, `not_run == 0`, `skipped == 0`, `failed == 0` in raw eval_report.json",
        "- **T2 ceiling_certified**: `fail=0`, `nr=0`, `sk>0`, `CEILING_CERT.md` present with per-skip structural rationale",
        "- **Never sum T1+T2 in headlines.** T2 is NOT a lock. Report as separate numbers.",
        "- Guard: `python3 scripts/pb_override_scan.py --guard` must pass 0 violations before archiving any lock.",
        "",
        "## Cluster / Transfer Map",
        "",
        "Completing a tool often transfers directly to its siblings. Key clusters:",
        "",
        "| Cluster | Tools | Transfer mechanism |",
        "|---------|-------|-------------------|",
        "| JSON ecosystem | jq · yq · xq · gron · dsq · trdsql · fx · fselect | Filter/transform DSL, streaming JSON parse |",
        "| Rust sharkdp | ripgrep · fd · bat · hexyl | Shared CLI conventions, clap arg parsing |",
        "| Disk usage | dust · duc · dua-cli · gdu · dutree | TUI tree rendering, du syscall patterns |",
        "| Terminal image | ascii-image-converter · jp2a · chafa · pixterm | ANSI escape rendering, image decode |",
        "| Compressors | lz4 · zstd · brotli · pigz · xz | Streaming block API, frame format |",
        "| Log analysis | angle-grinder · fblog · rhit · lnav | Log parsing, field extraction, aggregation |",
        "| Go linters | errcheck · go-critic · revive · wrapcheck | AST walk, pass/fail exit code, report format |",
        "| TUI explorers | fzf · broot · walk · xplr · felix · nnn | Tmux protocol, TUI key events, render loop |",
        "| Git TUI | lazygit · tig · stgit | Git plumbing API, TUI screen layout |",
        "",
    ]

    # ── What's-needed roadmap (sourced from build_knowledge.json) ──
    lines += section_roadmap()

    # ── T1 section ──────────────────────────────────────────────
    lines += section_t1(t1, residual_langs)

    # ── T2 section ──────────────────────────────────────────────
    lines += section_t2(t2, residual_langs)

    # ── T3 section ──────────────────────────────────────────────
    lines += section_t3(t3, residual_langs)

    # ── Alias appendix ──────────────────────────────────────────
    aliases = sorted([e for e in data if is_alias(e)], key=lambda e: e.get("slug", ""))
    lines += [
        "## Alias Rows (not counted in totals)",
        "",
        "These eval_index rows map to the same ProgramBench task as a canonical row above.",
        "",
        "| Alias slug | Canonical slug | Tests | Score |",
        "|-----------|----------------|-------|-------|",
    ]
    for e in aliases:
        alias_of = e.get("alias_of") or e.get("canonical_slug") or "?"
        lines.append(
            f"| `{e['slug']}` | `{alias_of}` | {e.get('official_total', '?')} | {score_str(e)} |"
        )
    lines += ["", "---", f"*Generated by `scripts/gen_pb_readme.py` · {now[:10]}*", ""]

    return "\n".join(lines)


def main():
    with open(INDEX, encoding="utf-8") as f:
        data = json.load(f)

    residual_langs = load_residual_langs()
    md = build_readme(data, residual_langs)
    OUT.write_text(md, encoding="utf-8")
    print(f"Written: {OUT}  ({len(md.splitlines())} lines)")

    # Quick sanity check
    canonical = [e for e in data if not is_alias(e)]
    t1 = [e for e in canonical if canonical_tier(e) == "strict_lock"]
    t2 = [e for e in canonical if canonical_tier(e) == "ceiling_certified"]
    t3 = [e for e in canonical if canonical_tier(e) == "open"]
    print(f"Counts: T1={len(t1)}  T2={len(t2)}  T3={len(t3)}  total={len(canonical)}")


if __name__ == "__main__":
    main()
