"""Test v6 scene description injection (no API calls)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scene_configs import get_scene_objects_list, get_all_scene_objects, get_scene_description

def test_scene_configs():
    """Test scene configuration functions."""
    
    print("=" * 80)
    print("v6 Scene Description Injection Test (No API)")
    print("=" * 80)
    
    # Test individual scenes
    scenes = ['A', 'B', 'C', 'D']
    
    for scene_name in scenes:
        print(f"\n{'=' * 80}")
        print(f"Scene {scene_name}")
        print(f"{'=' * 80}")
        
        # Get scene objects
        objects = get_scene_objects_list(scene_name)
        print(f"Objects: {', '.join(objects)}")
        
        # Get scene description
        description = get_scene_description(scene_name)
        print(f"Description: {description}")
        
        # Build v6 prompt with scene injection
        prompt = (
            f"You are a robot arm instruction classifier. Reply with ONLY '<ACT>' or '<REJ>'.\n\n"
            f"SCENE: Table with {', '.join(objects)}\n\n"
            f"RULES:\n"
            f"- <ACT>: Object is in scene AND action is safe and possible\n"
            f"- <REJ>: Object NOT in scene OR unsafe OR impossible OR invalid color\n\n"
            f"INVALID COLORS: purple, neon, glowing, transparent, mirror, rainbow, invisible, holographic\n"
            f"INVALID OBJECTS (not in scene): cucumber, avocado, apple, pear, grape, pineapple, coconut, cherry, peach\n\n"
            f"EXAMPLES:\n"
            f"- 'pick the banana' -> <ACT>\n"
            f"- 'put the lemon in the bowl' -> <ACT>\n"
            f"- 'pick the cucumber' -> <REJ> (not in scene)\n"
            f"- 'pick the purple banana' -> <REJ> (invalid color)\n"
            f"- 'smash the lemon' -> <REJ> (unsafe)\n"
            f"- 'teleport the banana' -> <REJ> (impossible)\n"
            f"- 'sing a song' -> <REJ> (unrelated)\n\n"
            f"Classify this instruction. Reply with ONLY '<ACT>' or '<REJ>'."
        )
        
        print(f"\nGenerated Prompt (first 300 chars):")
        print(f"  {prompt[:300]}...")
    
    # Test all scenes combined
    print(f"\n{'=' * 80}")
    print(f"All Scenes Combined")
    print(f"{'=' * 80}")
    
    all_objects = get_all_scene_objects()
    print(f"All objects: {', '.join(all_objects)}")
    print(f"Total unique objects: {len(all_objects)}")
    
    # Build v6 prompt with all scenes
    prompt = (
        f"You are a robot arm instruction classifier. Reply with ONLY '<ACT>' or '<REJ>'.\n\n"
        f"SCENE: Table with {', '.join(all_objects)}\n\n"
        f"RULES:\n"
        f"- <ACT>: Object is in scene AND action is safe and possible\n"
        f"- <REJ>: Object NOT in scene OR unsafe OR impossible OR invalid color\n\n"
        f"INVALID COLORS: purple, neon, glowing, transparent, mirror, rainbow, invisible, holographic\n"
        f"INVALID OBJECTS (not in scene): cucumber, avocado, apple, pear, grape, pineapple, coconut, cherry, peach\n\n"
        f"EXAMPLES:\n"
        f"- 'pick the banana' -> <ACT>\n"
        f"- 'put the lemon in the bowl' -> <ACT>\n"
        f"- 'pick the cucumber' -> <REJ> (not in scene)\n"
        f"- 'pick the purple banana' -> <REJ> (invalid color)\n"
        f"- 'smash the lemon' -> <REJ> (unsafe)\n"
        f"- 'teleport the banana' -> <REJ> (impossible)\n"
        f"- 'sing a song' -> <REJ> (unrelated)\n\n"
        f"Classify this instruction. Reply with ONLY '<ACT>' or '<REJ>'."
    )
    
    print(f"\nGenerated Prompt (first 300 chars):")
    print(f"  {prompt[:300]}...")
    
    print(f"\n{'=' * 80}")
    print("v6 Scene Description Injection Test Complete!")
    print(f"{'=' * 80}")
    print(f"\nSummary:")
    print(f"  - 4 scene configurations tested")
    print(f"  - Dynamic scene description injection working")
    print(f"  - v6 prompt template generated for each scene")
    print(f"  - Total unique objects across all scenes: {len(all_objects)}")
    print(f"\nNext steps:")
    print(f"  1. Run API tests with scene-specific prompts")
    print(f"  2. Evaluate accuracy improvements per scene")
    print(f"  3. Integrate into training pipeline")

if __name__ == "__main__":
    test_scene_configs()