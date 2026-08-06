import os
import glob
import re

count = 0
for root, dirs, files in os.walk("/home/philip/githome/"):
    dirs[:] = [d for d in dirs if d not in ('.git', 'target', 'node_modules', 'runs')]

    for f in files:
        if f.endswith(".xml"):
            path = os.path.join(root, f)
            try:
                with open(path, "r", encoding="utf-8") as f_in:
                    lines = f_in.readlines()
                
                new_lines = []
                modified = False
                for line in lines:
                    new_line = line
                    if 'alias_model_name=' in new_line:
                        new_line = re.sub(r'\s*alias_model_name="[^"]*"', '', new_line)
                    if 'chinese_name=' in new_line:
                        new_line = re.sub(r'\s*chinese_name="[^"]*"', '', new_line)
                    if 'english_name=' in new_line:
                        new_line = re.sub(r'\s*english_name="[^"]*"', '', new_line)
                    
                    if new_line != line:
                        modified = True
                    new_lines.append(new_line)
                
                if modified:
                    with open(path, "w", encoding="utf-8") as f_out:
                        f_out.writelines(new_lines)
                    count += 1
                    print(f"Fixed {path}")
            except Exception as e:
                pass

print(f"Total additional files fixed: {count}")
