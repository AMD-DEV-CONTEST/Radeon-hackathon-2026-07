
"""
ForgeMind Main Entry
Works on Windows, Linux, ROCm, Colab
"""
import os, sys
import pathlib
# Add project root to path
CURRENT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CURRENT_DIR))

import argparse

def main():
    parser = argparse.ArgumentParser(description="ForgeMind - Offline Dev Swarm")
    parser.add_argument("--model", default="qwen2.5-coder:1.5b")
    parser.add_argument("--rocm", action="store_true")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--workspace", default="demo/sample_codebase")
    args = parser.parse_args()

    print("="*60)
    print("🔥 ForgeMind - Sovereign Developer Swarm")
    print("AMD Radeon + ROCm | 100% Offline | Track 2")
    print("="*60)
    
    try:
        from app.rocm_utils import get_rocm_info
        info = get_rocm_info()
        print(f"GPU: {info.get('gpu_name','Unknown')}")
        print(f"ROCm: {info.get('rocm_version','N/A')}")
        print(f"VRAM: {info.get('vram_total_gb',0)} GB")
    except Exception as e:
        print(f"GPU info error (non-critical): {e}")

    from app.ui.gradio_app import create_ui
    ui = create_ui()
    ui.launch(server_name="0.0.0.0", server_port=args.port, share=False)

if __name__ == "__main__":
    main()
