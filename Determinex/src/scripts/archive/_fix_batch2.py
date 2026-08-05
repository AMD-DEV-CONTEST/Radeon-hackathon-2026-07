"""
Fix remaining bracket corruption in _gen_java_batch2.py.
Handles multi-line note strings that span 2 physical lines.
"""
import re, ast

INFILE = r'C:\Dev\Determinex\scripts\_gen_java_batch2.py'

with open(INFILE, 'r', encoding='utf-8') as f:
    content = f.read()

# After the previous fixer, remaining issues are:
#   '    ), "...part1 "\n       "...part2")\n'
# which should be:
#   '    ], "...part1 "\n       "...part2")\n'
#
# Also single-line:
#   '    ), "...note")\n'  ->  '    ], "...note")\n'
#
# Rule: any line that is EXACTLY:
#   ^    \), "  (note content starting — the list closer with a note)
# preceded by a line ending with '",\n'

lines = content.splitlines(keepends=True)
fixed = 0
new_lines = []
i = 0
while i < len(lines):
    ln = lines[i]
    # Match: '    ), "...'  (note-with-list-close pattern)
    if re.match(r'^    \), "', ln):
        prev = lines[i-1].rstrip() if i > 0 else ''
        if prev.endswith('",') or prev.endswith('"'):
            ln = '    ],' + ln[5:]  # replace '    ),' with '    ],'
            fixed += 1
    new_lines.append(ln)
    i += 1

with open(INFILE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f'Fixed {fixed} additional lines')

# Verify
with open(INFILE, 'r', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print('Syntax OK!')
except SyntaxError as e:
    print(f'Still broken at line {e.lineno}: {e.msg}')
    src_lines = src.splitlines()
    start = max(0, e.lineno - 5)
    end   = min(len(src_lines), e.lineno + 5)
    for j, sl in enumerate(src_lines[start:end], start + 1):
        marker = '>>>' if j == e.lineno else '   '
        print(f'{marker} {j:4d}: {sl!r}')
