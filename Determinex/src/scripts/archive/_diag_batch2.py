"""
Check actual byte content of problematic area and find the true parse error.
Try compiling smaller chunks to isolate.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

INFILE = r'C:\Dev\Determinex\scripts\_gen_java_batch2.py'

with open(INFILE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Try to parse progressively larger chunks (10 lines at a time)
for end in range(10, len(lines) + 10, 10):
    chunk_lines = lines[:end]
    chunk = ''.join(chunk_lines)
    try:
        compile(chunk, '<test>', 'exec')
    except SyntaxError as e:
        if e.lineno <= end:
            print(f"Error appears at line {e.lineno} (chunk ends at {end})")
            print(f"  msg: {e.msg}")
            print(f"  text: {e.text!r}")
            # Show surrounding lines
            start_show = max(0, e.lineno - 5)
            end_show = min(len(lines), e.lineno + 3)
            for j, sl in enumerate(lines[start_show:end_show], start_show + 1):
                marker = '>>>' if j == e.lineno else '   '
                print(f"  {marker} {j:4d}: {sl!r}")
            break
    except Exception as e:
        pass
else:
    print("No syntax error found — file is OK!")
