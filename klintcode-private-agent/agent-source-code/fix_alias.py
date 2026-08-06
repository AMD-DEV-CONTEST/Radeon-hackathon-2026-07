import os
import glob

dirs_to_search = [
    "/home/philip/githome/flint-code/benchmarks/tasks/",
    "/home/philip/githome/flint-code/30obj-success-output/models/"
]

count = 0
for d in dirs_to_search:
    for root, dirs, files in os.walk(d):
        for f in files:
            if f.endswith(".xml"):
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8") as f_in:
                    lines = f_in.readlines()
                
                new_lines = []
                modified = False
                for line in lines:
                    if 'alias_model_name=' in line:
                        # Just skip or remove the attribute
                        # If it's on its own line like `<root alias_model_name="..."\n` we might break XML if we just delete it
                        # Let's properly replace the substring
                        import re
                        new_line = re.sub(r'\s*alias_model_name="[^"]*"', '', line)
                        if new_line != line:
                            modified = True
                        new_lines.append(new_line)
                    else:
                        new_lines.append(line)
                
                if modified:
                    with open(path, "w", encoding="utf-8") as f_out:
                        f_out.writelines(new_lines)
                    count += 1
                    print(f"Fixed {path}")

print(f"Total files fixed: {count}")
