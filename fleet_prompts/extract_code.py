#!/usr/bin/env python3
"""
Extract code blocks from a fleet response and write them to the right paths.

Looks for markers like:
  // === FILE: src/foo.rs ===
  // === FILE: shaders/bar.wgsl ===

and writes the following code block to that path relative to the project root.
"""

import sys
import os
import re

def extract_and_write(response_file: str, project_root: str):
    with open(response_file, 'r') as f:
        content = f.read()

    # Find all FILE markers and their code blocks
    # Pattern: // === FILE: <path> === followed by optional ```lang and code
    file_pattern = re.compile(
        r'//\s*===\s*FILE:\s*([^\s=]+)\s*===\s*\n'  # marker line
        r'(?:```\w*\n)?'                              # optional ```lang
        r'(.*?)'                                      # code content
        r'(?:```\s*\n|(?=//\s*===\s*FILE:)|$)',      # end: ``` or next marker or EOF
        re.DOTALL
    )

    written = []
    skipped = []

    for match in file_pattern.finditer(content):
        rel_path = match.group(1).strip()
        code = match.group(2).strip()

        # Skip empty blocks
        if not code or len(code) < 20:
            skipped.append(f"SKIP (empty): {rel_path}")
            continue

        # Skip if it looks like pseudo-code (contains "// ..." or "// omitted")
        pseudo_markers = ['// ...', '// omitted', '// TODO', '// placeholder', 'pseudo-code']
        if any(m in code for m in pseudo_markers):
            skipped.append(f"SKIP (pseudo-code): {rel_path}")
            continue

        # Resolve path
        full_path = os.path.join(project_root, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Backup existing file
        if os.path.exists(full_path):
            backup = full_path + '.conductor_backup'
            with open(full_path, 'r') as f_orig:
                with open(backup, 'w') as f_bak:
                    f_bak.write(f_orig.read())

        with open(full_path, 'w') as f_out:
            f_out.write(code + '\n')

        written.append(f"WROTE: {rel_path} ({len(code)} chars)")

    for msg in written:
        print(msg)
    for msg in skipped:
        print(msg)

    if not written:
        print("WARNING: No files extracted. Check response format.")
        # Print first 500 chars of response for debugging
        print(f"Response preview: {content[:500]}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: extract_code.py <response_file> <project_root>")
        sys.exit(1)
    extract_and_write(sys.argv[1], sys.argv[2])
