"""Fix batch9: move Java // comments that leaked outside strings back inside."""
import re

path = r'C:\Dev\Determinex\scripts\_gen_java_batch9.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern: "...", // java comment
# Must become: "... // java comment",
# The string ends with "," then whitespace then // java comment
fixed = re.sub(
    r'("(?:[^"\\]|\\.)*"),(\s*//[^\n]*)',
    lambda m: '"' + m.group(1)[1:-1] + m.group(2).strip() + '",',
    content
)

# Actually simpler: just fix lines where a string ends and then has // comment after comma
lines = content.split('\n')
fixed_lines = []
count = 0
for line in lines:
    m = re.match(r'^(\s*"[^"]*"),\s*(//.*?)$', line)
    if m:
        # Embed the comment inside the string
        inner = m.group(1)[1:-1]  # strip outer quotes
        comment = m.group(2)
        fixed_line = m.group(1)[0:1] + inner + ' ' + comment + '",'
        # Get leading whitespace
        leading = len(line) - len(line.lstrip())
        fixed_lines.append(' ' * leading + '"' + inner + ' ' + comment + '",')
        count += 1
        print(f'Fixed: {line.strip()[:80]}')
    else:
        fixed_lines.append(line)

with open(path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(fixed_lines))

print(f'\nFixed {count} lines.')
