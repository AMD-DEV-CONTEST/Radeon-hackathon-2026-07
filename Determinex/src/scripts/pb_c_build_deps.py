#!/usr/bin/env python3
"""
Add proper build dependencies and build commands to C/C++ tool compile.sh files.
Replaces the bare `make 2>build.err || true` pattern with proper dep install + build.
Always writes LF endings (no CRLF on Windows).
"""

import sys
from pathlib import Path

OVERRIDES = Path("corpus/programbench/per_tool_overrides")

# Per-tool patches: (dir_pattern, old_build_block, new_build_block)
# old_build_block is the exact text to replace (after reading with LF normalization)
PATCHES = {
    "jonas__tig": {
        "old": (
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            "        make 2>build.err || true\n"
            "    fi\n"
            "    if [ ! -f ./tig ]; then\n"
            "        gcc -O2 -Wall -o tig *.c 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
            "chmod +x ./tig 2>/dev/null || true\n"
            "if [ -f ./tig ]; then\n"
            "    cp ./tig /usr/local/bin/tig\n"
            "fi\n"
        ),
        "new": (
            "apt-get update -qq 2>/dev/null && apt-get install -y -qq \\\n"
            "  build-essential pkg-config libncurses-dev libncursesw5-dev \\\n"
            "  libreadline-dev 2>/dev/null || true\n"
            "\n"
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    [ -f autogen.sh ] && [ ! -f configure ] && sh autogen.sh 2>/dev/null || true\n"
            "    [ -f configure ] && [ ! -f Makefile ] && \\\n"
            "        ./configure --prefix=/usr/local 2>/dev/null || true\n"
            "    if [ -f Makefile ]; then\n"
            '        make -j"$(nproc 2>/dev/null || echo 2)" prefix=/usr/local 2>build.err || \\\n'
            "        make prefix=/usr/local 2>>build.err || true\n"
            '        for c in src/tig ./tig; do [ -f "$c" ] && cp "$c" /usr/local/bin/tig && break; done || true\n'
            "    fi\n"
            "    [ ! -f /usr/local/bin/tig ] && \\\n"
            "        gcc -O2 -o tig *.c -lncurses -lreadline 2>>build.err && \\\n"
            "        cp tig /usr/local/bin/tig || true\n"
            "fi\n"
            "chmod +x /usr/local/bin/tig 2>/dev/null || true\n"
        ),
    },
    "jarun__nnn": {
        "old": (
            "if command -v make >/dev/null 2>&1 && [ -f Makefile ]; then\n"
            "    make 2>build.err || true\n"
            "fi\n"
            "if [ ! -f ./nnn ] && command -v cmake >/dev/null 2>&1 && [ -f CMakeLists.txt ]; then\n"
            "    mkdir -p build\n"
            "    (cd build && cmake .. && cmake --build .) 2>>build.err || true\n"
            "    find build -type f -perm -111 -name 'nnn' -exec cp {} ./nnn \\; 2>/dev/null || true\n"
            "fi\n"
            "if [ ! -f ./nnn ] && command -v g++ >/dev/null 2>&1; then\n"
            "    g++ -O2 -std=c++17 -o nnn $(find . -name '*.cpp' -not -path './build/*' | head -200) 2>>build.err || true\n"
            "fi\n"
            "chmod +x ./nnn 2>/dev/null || true\n"
            "if [ -f ./nnn ]; then\n"
            "    cp ./nnn /usr/local/bin/nnn\n"
            "fi\n"
        ),
        "new": (
            "apt-get update -qq 2>/dev/null && apt-get install -y -qq \\\n"
            "  build-essential pkg-config libncurses-dev libncursesw5-dev \\\n"
            "  libreadline-dev libpcre2-dev 2>/dev/null || true\n"
            "\n"
            "if command -v make >/dev/null 2>&1 && [ -f Makefile ]; then\n"
            '    make -j"$(nproc 2>/dev/null || echo 2)" O_PCRE=1 2>build.err || \\\n'
            '    make -j"$(nproc 2>/dev/null || echo 2)" 2>>build.err || \\\n'
            "    make 2>>build.err || true\n"
            "fi\n"
            "chmod +x ./nnn 2>/dev/null || true\n"
            "if [ -f ./nnn ]; then\n"
            "    cp ./nnn /usr/local/bin/nnn\n"
            "fi\n"
        ),
    },
    "lfos__calcurse": {
        "old": (
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            "        make 2>build.err || true\n"
            "    fi\n"
            "    if [ ! -f ./calcurse ]; then\n"
            "        gcc -O2 -Wall -o calcurse *.c 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
            "chmod +x ./calcurse 2>/dev/null || true\n"
            "if [ -f ./calcurse ]; then\n"
            "    cp ./calcurse /usr/local/bin/calcurse\n"
            "fi\n"
        ),
        "new": (
            "apt-get update -qq 2>/dev/null && apt-get install -y -qq \\\n"
            "  build-essential pkg-config autoconf automake \\\n"
            "  libncurses-dev libncursesw5-dev libical-dev 2>/dev/null || true\n"
            "\n"
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    [ -f autogen.sh ] && sh autogen.sh 2>/dev/null || true\n"
            "    [ -f configure.ac ] && [ ! -f configure ] && autoreconf -fi 2>/dev/null || true\n"
            "    [ -f configure ] && [ ! -f Makefile ] && \\\n"
            "        ./configure --prefix=/usr/local 2>/dev/null || true\n"
            "    if [ -f Makefile ]; then\n"
            '        make -j"$(nproc 2>/dev/null || echo 2)" 2>build.err || make 2>>build.err || true\n'
            '        for c in src/calcurse ./calcurse; do [ -f "$c" ] && cp "$c" /usr/local/bin/calcurse && break; done || true\n'
            "    fi\n"
            "fi\n"
            "chmod +x /usr/local/bin/calcurse 2>/dev/null || true\n"
        ),
    },
    "tinycc__tinycc": {
        "old": (
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            "        make VERSION=0.9.28 2>build.err || true\n"
            "    fi\n"
            "    if [ ! -f ./tinycc ]; then\n"
            "        gcc -O2 -Wall -DTCC_VERSION='\"0.9.28\"' -o tinycc *.c 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
        "new": (
            "apt-get update -qq 2>/dev/null && apt-get install -y -qq build-essential 2>/dev/null || true\n"
            "\n"
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            '        make -j"$(nproc 2>/dev/null || echo 2)" VERSION=0.9.28 2>build.err || \\\n'
            "        make VERSION=0.9.28 2>>build.err || true\n"
            "    fi\n"
            "    if [ ! -f ./tinycc ]; then\n"
            "        gcc -O2 -Wall -DTCC_VERSION='\"0.9.28\"' -o tinycc *.c 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
    },
    "lua__lua": {
        "old": (
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            "        make 2>build.err || true\n"
            "    fi\n"
            "    if [ ! -f ./lua ]; then\n"
            "        gcc -O2 -Wall -o lua *.c 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
        "new": (
            "apt-get update -qq 2>/dev/null && apt-get install -y -qq \\\n"
            "  build-essential libreadline-dev 2>/dev/null || true\n"
            "\n"
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            '        make -j"$(nproc 2>/dev/null || echo 2)" linux 2>build.err || \\\n'
            "        make linux 2>>build.err || make 2>>build.err || true\n"
            "    fi\n"
            "    if [ ! -f ./lua ]; then\n"
            "        gcc -O2 -Wall -o lua *.c -lm -lreadline -ldl 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
    },
    "luajit__luajit": {
        "old": (
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            "        make 2>build.err || true\n"
            "    fi\n"
            "    if [ ! -f ./luajit ]; then\n"
            "        gcc -O2 -Wall -o luajit *.c 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
        "new": (
            "apt-get update -qq 2>/dev/null && apt-get install -y -qq build-essential 2>/dev/null || true\n"
            "\n"
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            '        make -j"$(nproc 2>/dev/null || echo 2)" BUILDMODE=static 2>build.err || \\\n'
            "        make 2>>build.err || true\n"
            "        # LuaJIT binary is at src/luajit\n"
            "        [ ! -f ./luajit ] && [ -f src/luajit ] && cp src/luajit ./luajit || true\n"
            "    fi\n"
            "    if [ ! -f ./luajit ]; then\n"
            "        gcc -O2 -Wall -o luajit *.c -lm -ldl 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
    },
    "samtools__samtools": {
        "old": (
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            "        make 2>build.err || true\n"
            "    fi\n"
            "    if [ ! -f ./samtools ]; then\n"
            "        gcc -O2 -Wall -o samtools *.c 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
        "new": (
            "apt-get update -qq 2>/dev/null && apt-get install -y -qq \\\n"
            "  build-essential zlib1g-dev libbz2-dev liblzma-dev \\\n"
            "  libncurses-dev libcurl4-openssl-dev libssl-dev 2>/dev/null || true\n"
            "\n"
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            '        make -j"$(nproc 2>/dev/null || echo 2)" 2>build.err || make 2>>build.err || true\n'
            "    fi\n"
            "fi\n"
        ),
    },
    "robertdavidgraham__masscan": {
        "old": (
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            "        make 2>build.err || true\n"
            "    fi\n"
            "    if [ ! -f ./masscan ]; then\n"
            "        gcc -O2 -Wall -o masscan *.c 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
        "new": (
            "apt-get update -qq 2>/dev/null && apt-get install -y -qq \\\n"
            "  build-essential libpcap-dev 2>/dev/null || true\n"
            "\n"
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            '        make -j"$(nproc 2>/dev/null || echo 2)" 2>build.err || make 2>>build.err || true\n'
            "    fi\n"
            "    if [ ! -f ./masscan ]; then\n"
            "        gcc -O2 -Wall -o masscan *.c -lpcap 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
    },
    "mkj__dropbear": {
        "old": (
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    if [ -f Makefile ]; then\n"
            "        make 2>build.err || true\n"
            "    fi\n"
            "    if [ ! -f ./dropbear ]; then\n"
            "        gcc -O2 -Wall -o dropbear *.c 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
        "new": (
            "apt-get update -qq 2>/dev/null && apt-get install -y -qq \\\n"
            "  build-essential autoconf automake zlib1g-dev libssl-dev 2>/dev/null || true\n"
            "\n"
            "if command -v gcc >/dev/null 2>&1; then\n"
            "    [ -f configure.ac ] && [ ! -f configure ] && autoreconf -fi 2>/dev/null || true\n"
            "    [ -f configure ] && [ ! -f Makefile ] && \\\n"
            "        ./configure --prefix=/usr/local --disable-syslog 2>/dev/null || true\n"
            "    if [ -f Makefile ]; then\n"
            '        make -j"$(nproc 2>/dev/null || echo 2)" PROGRAMS=dropbear 2>build.err || \\\n'
            "        make 2>>build.err || true\n"
            "    fi\n"
            "fi\n"
        ),
    },
}


def fix_tool(dir_name: str, patch: dict, dry_run: bool = False) -> str:
    matches = [d for d in OVERRIDES.iterdir() if d.is_dir() and d.name.startswith(dir_name)]
    if not matches:
        return f"NO DIR: {dir_name}"

    results = []
    for d in matches:
        sh = d / "compile.sh"
        if not sh.exists():
            results.append(f"NO compile.sh: {d.name}")
            continue

        raw = sh.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        content = raw.decode("utf-8", errors="replace")

        old = patch["old"]
        if old not in content:
            results.append(f"NO MATCH: {d.name}")
            continue

        new_content = content.replace(old, patch["new"], 1)
        if dry_run:
            results.append(f"[DRY] {d.name}")
        else:
            sh.write_bytes(new_content.encode("utf-8"))
            results.append(f"[FIX] {d.name}")

    return " | ".join(results)


def main():
    dry_run = "--dry-run" in sys.argv
    for tool_prefix, patch in PATCHES.items():
        result = fix_tool(tool_prefix, patch, dry_run)
        print(result)


if __name__ == "__main__":
    main()
