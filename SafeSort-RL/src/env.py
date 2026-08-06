"""
PyBullet environment for waste sorting task.
Day 1 implementation - minimal, working version.
"""

import pybullet as p
import pybullet_data
import gymnasium as gym
import numpy as np
from typing import Tuple, Dict


class WasteSortingEnv(gym.Env):
    """
    Waste sorting environment.
    - Objects: battery, chemical_bottle, plastic_bottle, syringe
    - Bins: hazard_bin, recycle_bin
    - Task: sort objects into correct bins based on instruction
    """
    
    def __init__(self, use_gui=False):
        self.use_gui = use_gui
        self.client = p.connect(p.GUI if use_gui else p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -9.81)
        p.setPhysicsEngineParameter(numSubSteps=5)
        
        # Object metadata
        self.object_types = ["battery", "chemical_bottle", "plastic_bottle", "syringe"]
        self.hazardous_objects = {"battery", "chemical_bottle", "syringe"}
        self.safe_objects = {"plastic_bottle"}
        
        # Bin positions
        self.bins = {
            "hazard": np.array([0.4, 0.4, 0.1]),
            "recycle": np.array([-0.4, 0.4, 0.1]),
        }
        
        # Load static objects
        self.plane = p.loadURDF("plane.urdf")
        self.table = p.loadURDF("table/table.urdf", basePosition=[0, 0, -0.05])
        
        # Simple gripper (cube)
        self.gripper = p.loadURDF("r2d2.urdf", basePosition=[0, 0, 0.5])
        self.gripper_home = np.array([0, 0, 0.5])
        
        # Workspace bounds
        self.workspace = {
            "x": (-0.3, 0.3),
            "y": (-0.3, 0.3),
            "z": (0.05, 1.0)
        }
        
        # State
        self.objects = {}  # object_type -> body_id
        self.grasped_object = None
        self.step_count = 0
        self.max_steps = 200
        
        # Observation/action spaces
        self.observation_space = gym.spaces.Box(0, 255, shape=(64, 64, 3), dtype=np.uint8)
        self.action_space = gym.spaces.Box(-1, 1, shape=(5,), dtype=np.float32)
        
        # Current instruction
        self.current_instruction = None
        self.instruction_embedding = None
    
    def reset(self, seed=None, options=None):
        # Clear objects
        for body_id in self.objects.values():
            try:
                p.removeBody(body_id)
            except:
                pass
        self.objects = {}
        self.grasped_object = None
        self.step_count = 0
        
        # Spawn 4 random objects
        object_order = np.random.permutation(self.object_types)
        for obj_type in object_order[:4]:
            x = np.random.uniform(-0.2, 0.2)
            y = np.random.uniform(-0.2, 0.2)
            z = 0.1
            
            # Load simple shapes as objects
            obj_id = p.loadURDF("cube.urdf", basePosition=[x, y, z])
            self.objects[obj_type] = obj_id
        
        # Sample random instruction
        self.current_instruction = self._sample_instruction()
        self.instruction_embedding = np.random.randn(512).astype(np.float32)  # Will be CLIP encoding
        
        # Reset gripper
        p.resetBasePositionAndOrientation(self.gripper, self.gripper_home, [0, 0, 0, 1])
        
        return self._get_observation(), {}
    
    def step(self, action):
        """
        action: (dx, dy, dz, rotation, grasp)
        - Each component in [-1, 1]
        - Grasp: >0.5 = close, <=0.5 = open
        """
        # Get current gripper state
        pos, orn = p.getBasePositionAndOrientation(self.gripper)
        
        # Decode action
        dx, dy, dz, rotation, grasp = action
        
        # Compute new position
        new_x = np.clip(pos[0] + dx * 0.05, self.workspace["x"][0], self.workspace["x"][1])
        new_y = np.clip(pos[1] + dy * 0.05, self.workspace["y"][0], self.workspace["y"][1])
        new_z = np.clip(pos[2] + dz * 0.05, self.workspace["z"][0], self.workspace["z"][1])
        
        # Move gripper
        new_orn = p.getQuaternionFromEuler([0, 0, rotation * np.pi])
        p.resetBasePositionAndOrientation(self.gripper, [new_x, new_y, new_z], new_orn)
        
        # Grasp logic (simplified)
        if grasp > 0.5:
            self._try_grasp([new_x, new_y, new_z])
        else:
            self._release_grasp()
        
        # Step simulation
        p.stepSimulation()
        
        # Compute reward
        reward = self._compute_reward()
        
        # Check done
        self.step_count += 1
        done = self.step_count >= self.max_steps
        
        obs = self._get_observation()
        
        return obs, reward, done, False, {}
    
    def _try_grasp(self, gripper_pos):
        """Try to grasp object near gripper"""
        if self.grasped_object is not None:
            return  # Already grasping
        
        gripper_pos = np.array(gripper_pos)
        for obj_type, obj_id in self.objects.items():
            obj_pos, _ = p.getBasePositionAndOrientation(obj_id)
            obj_pos = np.array(obj_pos)
            
            dist = np.linalg.norm(gripper_pos - obj_pos)
            
            if dist < 0.15:  # Grasp distance
                self.grasped_object = obj_type
                return
    
    def _release_grasp(self):
        """Release grasped object"""
        self.grasped_object = None
    
    def _compute_reward(self):
        """Simple reward signal"""
        # Placeholder
        return -0.01  # Step penalty
    
    def _get_observation(self):
        """Render RGB image from above"""
        width, height = 64, 64
        
        # Camera looking down at table
        viewMatrix = p.computeViewMatrix(
            cameraEyePosition=[0, 0, 1.5],
            cameraTargetPosition=[0, 0, 0.1],
            cameraUpVector=[0, 1, 0]
        )
        projectionMatrix = p.computeProjectionMatrixFOV(
            fov=45, aspect=1.0, nearVal=0.01, farVal=5
        )
        
        _, _, rgbPixels, _, _ = p.getCameraImage(
            width, height, viewMatrix, projectionMatrix,
            renderer=p.ER_BULLET_HARDWARE_OPENGL
        )
        
        # Extract RGB (discard alpha)
        rgb = np.array(rgbPixels[:, :, :3], dtype=np.uint8)
        return rgb
    
    def _sample_instruction(self):
        """Sample random instruction"""
        instructions = [
            "Dispose of all hazardous waste.",
            "Recycle only the batteries.",
            "Collect plastic bottles.",
            "Remove dangerous materials.",
            "Sort hazardous items.",
        ]
        return np.random.choice(instructions)
    
    def close(self):
        p.disconnect(self.client)


def test_env():
    """Quick test"""
    env = WasteSortingEnv(use_gui=False)
    obs, _ = env.reset()
    
    print(f"Observation shape: {obs.shape}")
    print(f"Instruction: {env.current_instruction}")
    
    for step in range(10):
        action = env.action_space.sample()
        obs, reward, done, truncated, info = env.step(action)
        print(f"Step {step}: reward={reward:.3f}, obs_shape={obs.shape}")
        if done:
            break
    
    env.close()
    print("✓ Environment works!")


if __name__ == "__main__":
    test_env()
