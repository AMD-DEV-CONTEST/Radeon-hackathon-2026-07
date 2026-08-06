
# ===== FORGEMIND - COLAB ONE-CELL RUNNER =====
# Paste this ENTIRE cell in Colab

# 1. Clean and unzip (upload zip first to /content/)
import os, sys, pathlib
# If you uploaded zip manually, unzip it:
# !unzip -o /content/forgemind_fixed_WINDOWS_COLAB_READY.zip -d /content/

# 2. Fix Python path - THIS FIXES "ModuleNotFoundError: No module named 'app'"
PROJECT_ROOT = pathlib.Path("/content/forgemind_fixed")
if not PROJECT_ROOT.exists():
    # Try alternative path after unzip
    for p in ["/content/forgemind_fixed_WINDOWS_COLAB_READY", "/content/forgemind", "/content"]:
        if (pathlib.Path(p) / "app").exists():
            PROJECT_ROOT = pathlib.Path(p)
            break

print(f"Project root: {PROJECT_ROOT}")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "app"))
os.chdir(str(PROJECT_ROOT))

# 3. Install deps (ignore opentelemetry warning - it's harmless)
# !pip install -q -r requirements-colab.txt
# !pip install -q gradio==5.4.0 langgraph==0.2.39 chromadb==0.5.8 sentence-transformers==3.2.1 torch ollama

# 4. Launch
try:
    from app.ui.gradio_app import create_ui
    ui = create_ui()
    ui.launch(share=True, debug=False)
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    print("\nTrying alternative import...")
    from ui.gradio_app import create_ui
    ui = create_ui()
    ui.launch(share=True)
