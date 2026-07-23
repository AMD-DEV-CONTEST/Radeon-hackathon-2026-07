#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║  TEXTOVID — AI Comic Studio — One-Paste Deployer               ║
║  AMD AI DevMaster Hackathon 2026 — Track 1                      ║
║                                                                  ║
║  USAGE: Copy-paste this ENTIRE file into a JupyterLab           ║
║         notebook cell and run it.                                ║
║                                                                  ║
║  It will:                                                       ║
║  1. Extract the project files to /workspace/textovid/           ║
║  2. Install PyTorch ROCm + all dependencies                     ║
║  3. Verify GPU and show ready instructions                      ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os, sys, subprocess, base64, tarfile, io, time

print("\n" + "=" * 62)
print("  TEXTOVID — AI Comic Studio Setup")
print("  AMD AI DevMaster Hackathon 2026")
print("=" * 62 + "\n")

WORKSPACE = "/workspace"

# ──────────────────────────────────────────────────────────────────
# STEP 1: Extract project files from embedded tarball
# ──────────────────────────────────────────────────────────────────
print("[1/4] Extracting Textovid project files...")

# The tarball is embedded as base64 below this line.
# To update:  cd /path/to/textovid && tar czf - . | base64 -w72
B64_DATA = r"""
__TARBALL_PLACEHOLDER__
"""

if B64_DATA.strip() == "__TARBALL_PLACEHOLDER__":
    print("  [INFO] No embedded tarball — using live file creation fallback.")
    # Fallback: create files directly if no tarball embedded
    os.makedirs(f"{WORKSPACE}/textovid", exist_ok=True)

    FILES = {
        "config.py": "",       # Will be populated by the install script
        "app.py": "",
        "story_engine.py": "",
        "image_engine.py": "",
        "video_engine.py": "",
        "comic_layout.py": "",
        "uniqueness.py": "",
        "gpu_utils.py": "",
        "style.css": "",
        "requirements.txt": "",
        "README.md": "",
    }
    print("  [ACTION NEEDED] Upload the textovid/ folder to /workspace/ manually,")
    print("  or re-generate the deploy script with embedded tarball.")
else:
    try:
        tar_bytes = base64.b64decode(B64_DATA.strip())
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            tar.extractall(WORKSPACE)
        print(f"  ✓ Extracted to {WORKSPACE}/textovid/")
    except Exception as e:
        print(f"  ✗ Tarball extraction failed: {e}")
        print("  Upload the textovid/ folder to /workspace/ manually.")

# ──────────────────────────────────────────────────────────────────
# STEP 2: Install PyTorch with ROCm support
# ──────────────────────────────────────────────────────────────────
print("\n[2/4] Installing PyTorch ROCm (this takes 2-5 minutes)...")

rocm_urls = [
    "https://download.pytorch.org/whl/rocm6.2",
    "https://download.pytorch.org/whl/rocm6.1",
    "https://download.pytorch.org/whl/rocm6.0",
]

torch_installed = False
for url in rocm_urls:
    print(f"  Trying: {url}")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet",
         "torch", "torchvision", "torchaudio",
         "--index-url", url],
        capture_output=True, text=True, timeout=300,
    )
    if r.returncode == 0:
        torch_installed = True
        print(f"  ✓ PyTorch installed from {url}")
        break
    else:
        print(f"  ✗ Failed: {r.stderr[:200]}")

if not torch_installed:
    print("  ⚠ ROCm wheels not found. Trying default PyTorch...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet",
         "torch", "torchvision", "torchaudio"],
        timeout=300,
    )

# ──────────────────────────────────────────────────────────────────
# STEP 3: Install Python dependencies
# ──────────────────────────────────────────────────────────────────
print("\n[3/4] Installing diffusers, gradio, and other dependencies...")

deps = [
    "diffusers>=0.30.0",
    "transformers>=4.42.0",
    "accelerate>=0.33.0",
    "gradio>=4.40.0",
    "Pillow>=10.0.0",
    "requests>=2.31.0",
    "safetensors>=0.4.0",
    "imageio>=2.34.0",
    "imageio-ffmpeg>=0.5.1",
]

r = subprocess.run(
    [sys.executable, "-m", "pip", "install", "--quiet"] + deps,
    timeout=300,
)
if r.returncode == 0:
    print("  ✓ All dependencies installed")
else:
    print(f"  ⚠ Some deps may have failed. Check the output above.")

# ──────────────────────────────────────────────────────────────────
# STEP 4: Verify installation
# ──────────────────────────────────────────────────────────────────
print("\n[4/4] Verifying installation...\n")

print("  " + "-" * 50)
try:
    import torch
    print(f"  PyTorch:     {torch.__version__}")
    print(f"  CUDA/HIP:    {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  GPU:         {torch.cuda.get_device_name(0)}")
        try:
            props = torch.cuda.get_device_properties(0)
            print(f"  VRAM:        {round(props.total_mem / 1e9, 2)} GB")
        except: pass
        try:
            print(f"  ROCm:        {torch.version.hip}")
        except: pass
    else:
        print("  ⚠ WARNING: No GPU detected! Check ROCm installation.")
except Exception as e:
    print(f"  ⚠ PyTorch import failed: {e}")

try:
    import diffusers
    print(f"  Diffusers:   {diffusers.__version__}")
except: print("  ⚠ diffusers not found")

try:
    import gradio
    print(f"  Gradio:      {gradio.__version__}")
except: print("  ⚠ gradio not found")

try:
    import PIL
    print(f"  Pillow:      {PIL.__version__}")
except: print("  ⚠ Pillow not found")

print("  " + "-" * 50)

# ──────────────────────────────────────────────────────────────────
# READY
# ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 62)
print("  ✅ SETUP COMPLETE!")
print("=" * 62)
print("""
  NEXT STEPS:
  ────────────

  1. Get your FREE API key:
     → https://developer.amd.com.cn/radeon/modelapis
     → Click "Token Factory" and generate a key

  2. Start Textovid:
     cd /workspace/textovid && python app.py

  3. Open the URL shown (usually http://0.0.0.0:7860)

  4. Paste your API key in the UI and generate comics!

  TIPS:
  ─────
  • First generation will be slow (model download ~7GB).
    Subsequent runs are fast.
  • Use "Short (3 pages)" for testing — only 12 panels.
  • Uncheck "High-Res Fix" for faster (but lower quality) output.
  • Run the GPU Benchmark to get performance stats for your
    hackathon submission.
  • All generated comics are saved in /workspace/textovid/output/
""")