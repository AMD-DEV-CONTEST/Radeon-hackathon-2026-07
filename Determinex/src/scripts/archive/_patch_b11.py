import io

path = r'C:\Dev\Determinex\scripts\_gen_java_batch11.py'
lines = io.open(path, encoding='utf-8').readlines()

# Line 1828 (index 1827) has a stray trailing quote making it unterminated.
# Replace with a clean line that has no Java comparison operator issues.
old = lines[1827]
# The corrected line: just the loop header with the Java comment folded in (no ">")
new = '"            for (int w=capacity; w>=weights[i]; w--) // backwards\",\n'
lines[1827] = new
io.open(path, 'w', encoding='utf-8').writelines(lines)
print("Patched line 1828")
print("Old:", repr(old[:100]))
print("New:", repr(new))
