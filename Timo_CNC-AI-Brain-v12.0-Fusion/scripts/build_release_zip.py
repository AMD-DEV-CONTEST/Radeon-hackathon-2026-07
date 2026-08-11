"""Build the release ZIP for CNC-AI-Brain v12.0 Fusion.

Excludes: .venv, __pycache__, .pytest_cache, logs, .git, data/uploads,
*.log, tmp_*.json, chat_req.json, chat_resp*.json, *.pyc, .DS_Store.
"""
import fnmatch
import os
import sys
import zipfile

src_root = r"C:\Users\miscd\Desktop\比赛\摩尔\新建文件夹\CNC-AI-Brain-v12.0-Fusion\cnc-ai-brain"
zip_path = r"C:\Users\miscd\Desktop\比赛\摩尔\新建文件夹\CNC-AI-Brain-v12.0-Fusion\CNC-AI-Brain-v12.0-Fusion.zip"
top_dir = "CNC-AI-Brain-v12.0-Fusion"

exclude_dirs = {".venv", "__pycache__", ".pytest_cache", "logs", ".git", ".idea", ".vscode"}
exclude_patterns = [
    "*.log",
    "tmp_*.json",
    "chat_req.json",
    "chat_resp*.json",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "Thumbs.db",
]

# data/uploads is excluded but we keep the data/ directory structure (with a .gitkeep)
# data/step and data/stl are also excluded (generated content)
exclude_data_subdirs = {"uploads", "step", "stl"}

file_count = 0
skipped_count = 0

# Remove existing ZIP if present
if os.path.exists(zip_path):
    os.remove(zip_path)

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for root, dirs, files in os.walk(src_root):
        # Exclude top-level dirs by name
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        # Handle data/ subdirs: skip uploads/step/stl contents but keep dir
        rel_root = os.path.relpath(root, src_root)
        if rel_root == "data":
            # We will add a .gitkeep for uploads later; skip walking into excluded subdirs
            dirs[:] = [d for d in dirs if d not in exclude_data_subdirs]

        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, src_root)

            # Skip files inside data/uploads, data/step, data/stl (safety net)
            norm_rel = rel.replace("\\", "/")
            for sub in exclude_data_subdirs:
                if norm_rel.startswith(f"data/{sub}/") or norm_rel == f"data/{sub}":
                    skipped_count += 1
                    break
            else:
                # Skip files matching exclude patterns
                if any(fnmatch.fnmatch(f, p) for p in exclude_patterns):
                    skipped_count += 1
                    continue

                arcname = top_dir + "/" + norm_rel
                zf.write(full, arcname)
                file_count += 1

    # Add .gitkeep markers for empty excluded data subdirs so structure is visible
    for sub in exclude_data_subdirs:
        zf.writestr(f"{top_dir}/data/{sub}/.gitkeep", "")
        file_count += 1

zip_size_mb = os.path.getsize(zip_path) / 1024 / 1024
print(f"ZIP created: {zip_path}")
print(f"ZIP size: {zip_size_mb:.2f} MB")
print(f"Files included: {file_count}")
print(f"Files skipped: {skipped_count}")