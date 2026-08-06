"""Genesis Simulation Rendering - Screenshots and Video for RationalVLA Demo."""

import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import genesis as gs
import cv2

from build_scene import build_scene
from scene_configs import get_scene_layout

# Output directory
OUTPUT_DIR = _ROOT / "outputs" / "rationalvla" / "results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def render_scene(scene_name: str):
    """Render Genesis scene and save screenshots + video."""
    
    print(f"Initializing Genesis...")
    gs.init(backend=gs.cpu)
    
    print(f"Building scene: {scene_name}")
    scene_bundle = build_scene(scene_id=scene_name, show_viewer=False, add_video_cam=True)
    scene = scene_bundle.scene
    franka = scene_bundle.franka
    world_cam = scene_bundle.world_cam
    video_cam = scene_bundle.video_cam
    
    print(f"Scene built successfully")
    print(f"world_cam: {world_cam}")
    print(f"video_cam: {video_cam}")
    
    # Reset scene
    scene.reset()
    
    # Wait for physics to settle
    for _ in range(100):
        scene.step()
    
    # Render screenshots
    print("\nRendering screenshots...")
    
    if world_cam is not None:
        print("Rendering world_cam...")
        result = world_cam.render(rgb=True)
        img = result[0] if isinstance(result, (list, tuple)) else result
        if img.dtype != np.uint8:
            if img.max() <= 1.0:
                img = (img * 255).astype(np.uint8)
            else:
                img = img.astype(np.uint8)
        save_path = OUTPUT_DIR / f"scene_{scene_name}_world_view.png"
        cv2.imwrite(str(save_path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        print(f"  Saved: {save_path} (shape: {img.shape})")
    
    if video_cam is not None:
        print("Rendering video_cam...")
        result = video_cam.render(rgb=True)
        img = result[0] if isinstance(result, (list, tuple)) else result
        if img.dtype != np.uint8:
            if img.max() <= 1.0:
                img = (img * 255).astype(np.uint8)
            else:
                img = img.astype(np.uint8)
        save_path = OUTPUT_DIR / f"scene_{scene_name}_video_view.png"
        cv2.imwrite(str(save_path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        print(f"  Saved: {save_path} (shape: {img.shape})")
    
    # Record video
    print("\nRecording simulation video...")
    video_path = OUTPUT_DIR / f"scene_{scene_name}_simulation.mp4"
    
    num_frames = 100
    fps = 30
    
    frames = []
    for i in range(num_frames):
        scene.step()
        
        if video_cam is not None:
            result = video_cam.render(rgb=True)
            img = result[0] if isinstance(result, (list, tuple)) else result
            if img.dtype != np.uint8:
                if img.max() <= 1.0:
                    img = (img * 255).astype(np.uint8)
                else:
                    img = img.astype(np.uint8)
            frames.append(img)
        
        if i % 20 == 0:
            print(f"  Frame {i}/{num_frames}")
    
    if frames:
        print(f"Saving video to {video_path}...")
        h, w = frames[0].shape[:2]
        out = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
        for frame in frames:
            out.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        out.release()
        print(f"  Saved: {video_path}")
    
    print(f"\n{'='*60}")
    print(f"All results saved to: {OUTPUT_DIR}")
    print(f"{'='*60}")


def main():
    print("="*60)
    print("Genesis Simulation Rendering")
    print("="*60)
    
    render_scene("A")


if __name__ == "__main__":
    main()