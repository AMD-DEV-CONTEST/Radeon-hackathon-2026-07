"""Test v6 prompt with dynamic scene injection in RationalVLA model."""

import os
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Set API credentials
os.environ["LLM_API_KEY"] = "rc-1f14870349523ab224b071ef79b6c551cf582fe79bd8fc82"
os.environ["LLM_BASE_URL"] = "https://developer.amd.com.cn/radeon/api/v1"
os.environ["LLM_MODEL_ID"] = "DeepSeek-V4-Flash"

from rationalvla_model import build_rationalvla, APIMLLM

def test_scene_injection():
    """Test dynamic scene description injection for all 4 scenes."""
    
    print("=" * 80)
    print("RationalVLA v6 Dynamic Scene Injection Test")
    print("=" * 80)
    
    scenes = ['A', 'B', 'C', 'D']
    test_instructions = [
        ('pick the banana', 'ACT'),
        ('pick the cucumber', 'REJ'),
        ('put the red block in the red box', 'ACT'),
        ('stack the red block on the blue block', 'ACT'),
        ('pick the purple banana', 'REJ'),
        ('smash the lemon', 'REJ'),
        ('teleport the banana', 'REJ'),
        ('sing a song', 'REJ'),
    ]
    
    for scene_name in scenes:
        print(f"\n{'=' * 80}")
        print(f"Testing Scene {scene_name}")
        print(f"{'=' * 80}")
        
        # Build model with scene-specific prompt
        model = build_rationalvla(
            use_api=True,
            scene_name=scene_name,
        )
        
        # Get the API MLLM
        api_mllm = model.api_mllm
        print(f"\nScene Description: {api_mllm.scene_description}")
        print(f"System Prompt (first 200 chars): {api_mllm.SYSTEM_PROMPT[:200]}...")
        
        # Test a few instructions
        print(f"\nTesting instructions:")
        for instruction, expected in test_instructions[:4]:  # Test first 4
            response = api_mllm.classify(instruction)
            predicted = response.token.replace("<", "").replace(">", "")
            match = "✓" if predicted == expected else "✗"
            print(f"  {match} '{instruction}' → {predicted} (expected: {expected})")
            time.sleep(0.5)  # Small delay between API calls
        
        print()

def test_all_scenes_combined():
    """Test with all scenes combined (default)."""
    
    print(f"\n{'=' * 80}")
    print("Testing All Scenes Combined (Default)")
    print(f"{'=' * 80}")
    
    model = build_rationalvla(
        use_api=True,
        scene_name=None,  # Default: all scenes
    )
    
    api_mllm = model.api_mllm
    print(f"\nScene Description: {api_mllm.scene_description}")
    
    # Test instructions from different scenes
    test_instructions = [
        ('pick the banana', 'ACT'),
        ('put the red block in the red box', 'ACT'),
        ('stack the red block on the blue block', 'ACT'),
        ('pick the cucumber', 'REJ'),
        ('pick the neon lemon', 'REJ'),
    ]
    
    print(f"\nTesting instructions:")
    for instruction, expected in test_instructions:
        response = api_mllm.classify(instruction)
        predicted = response.token.replace("<", "").replace(">", "")
        match = "✓" if predicted == expected else "✗"
        print(f"  {match} '{instruction}' → {predicted} (expected: {expected})")
        time.sleep(0.5)

if __name__ == "__main__":
    # Test individual scenes
    test_scene_injection()
    
    # Test all scenes combined
    test_all_scenes_combined()
    
    print("\n" + "=" * 80)
    print("v6 Dynamic Scene Injection Test Complete!")
    print("=" * 80)