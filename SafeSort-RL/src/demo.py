"""
Demo SafeSort policy with different instructions.
Day 3 implementation - showcase language conditioning.

Usage:
    python demo.py --gui
"""

import argparse
import itertools
import numpy as np
from stable_baselines3 import PPO

from env import WasteSortingEnv
from vision import CLIPDetector


def run_demo(use_gui=True, n_episodes=3):
    """Run demo with different instructions"""
    
    # Load trained model
    try:
        model = PPO.load("models/safesort_policy")
        print("✓ Loaded trained model")
    except FileNotFoundError:
        print("✗ Model not found. Train first: python train.py")
        return
    
    # Initialize vision detector
    detector = CLIPDetector()
    
    # Demo scenarios
    scenarios = [
        "Dispose of all hazardous waste.",
        "Recycle only the batteries.",
        "Collect plastic bottles.",
    ]
    
    # Create environment
    env = WasteSortingEnv(use_gui=use_gui)
    
    print("\n" + "="*60)
    print("SafeSort-RL Demo: Language-Conditioned Waste Sorting")
    print("="*60)
    
    selected_scenarios = itertools.islice(itertools.cycle(scenarios), n_episodes)

    for scenario_idx, scenario in enumerate(selected_scenarios):
        print(f"\n[Scenario {scenario_idx + 1}/{n_episodes}]")
        print(f"Instruction: {scenario}")
        print("-" * 60)
        
        obs, _ = env.reset()
        
        # Set instruction (in real version, would be passed to policy)
        env.current_instruction = scenario
        
        total_reward = 0
        objects_detected = []
        
        for step in range(100):
            # Predict action
            action, _ = model.predict(obs, deterministic=True)
            
            # Step environment
            obs, reward, done, _, _ = env.step(action)
            total_reward += reward
            
            # Detect object in frame
            if step % 10 == 0:
                probs, detected = detector.detect(obs)
                confidence = probs[np.argmax(probs)]
                objects_detected.append(f"{detected}({confidence:.1%})")
                
                if step == 0:
                    print(f"Step {step:3d}: Detected: {detected:20s} | Reward: {reward:7.3f}")
            
            if done or step >= 50:
                break
        
        print(f"Episode complete. Total reward: {total_reward:.2f}")
        print(f"Objects seen: {', '.join(objects_detected)}")
    
    env.close()
    print("\n" + "="*60)
    print("✓ Demo complete!")
    print("="*60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", action="store_true", help="Use PyBullet GUI")
    parser.add_argument("--episodes", type=int, default=3, help="Number of demo episodes")
    args = parser.parse_args()
    
    run_demo(use_gui=args.gui, n_episodes=args.episodes)
