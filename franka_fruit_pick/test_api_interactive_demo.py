"""Interactive demo: user types instructions, API classifies in real-time."""

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rationalvla_model import build_rationalvla

API_KEY = "rc-1f14870349523ab224b071ef79b6c551cf582fe79bd8fc82"
BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"

def main():
    scene = input("Scene (A/B/C/D, default=A): ").strip().upper() or "A"
    
    model = build_rationalvla(
        api_key=API_KEY,
        base_url=BASE_URL,
        model_id="DeepSeek-V4-Flash",
        use_api=True,
        scene_name=scene,
    )
    
    print(f"\n{'='*60}")
    print(f"RationalVLA Interactive API Demo")
    print(f"Scene: {scene}")
    print(f"Objects: {model.api_mllm.scene_description}")
    print(f"{'='*60}\n")
    print("Type instructions to classify. 'quit' to exit.\n")
    
    count = 0
    while True:
        try:
            instruction = input("Instruction> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
            
        if not instruction or instruction.lower() in ["quit", "exit", "q"]:
            print("Bye!")
            break
        
        count += 1
        start = time.time()
        resp = model.api_mllm.classify(instruction)
        elapsed = time.time() - start
        
        print(f"  → {resp.prediction} ({elapsed:.1f}s)\n")

if __name__ == "__main__":
    main()