"""
Scene Memory — Maintain scene state across frames.
Tracks object positions, supports multi-step tasks, enables verification.

Flow:
    1. Initialize with known objects
    2. Update positions after each action
    3. Query current state
    4. Compare before/after for verification
"""
import time
from typing import Dict, List, Optional


class SceneMemory:
    def __init__(self):
        self.objects = {}  # name → {position, last_seen, color, type}
        self.history = []  # List of snapshots
        self.task_log = []  # Log of executed actions

    def initialize(self, scene_objects: Dict):
        """Initialize with Genesis scene objects."""
        for name, entity in scene_objects.items():
            pos_raw = entity.get_pos()
            # Handle both tensor and numpy array returns
            if hasattr(pos_raw, 'cpu'):
                pos = pos_raw.cpu().numpy().tolist()
            elif hasattr(pos_raw, 'tolist'):
                pos = pos_raw.tolist()
            else:
                pos = list(pos_raw)
            self.objects[name] = {
                "position": pos,
                "initial_position": pos.copy(),
                "color": self._infer_color(name),
                "type": self._infer_type(name),
                "last_seen": time.time(),
                "moved": False,
            }
        self._snapshot("initial")

    def update_positions(self, scene_objects: Dict):
        """Update all object positions from Genesis."""
        for name, entity in scene_objects.items():
            if name in self.objects:
                new_pos = entity.get_pos().tolist()
                old_pos = self.objects[name]["position"]
                moved = sum(abs(new_pos[i] - old_pos[i]) for i in range(3)) > 0.01
                self.objects[name].update({
                    "position": new_pos,
                    "last_seen": time.time(),
                    "moved": moved,  # Current state, not latched
                })

    def record_action(self, action: str, object_name: str, target_name: str = None):
        """Record an executed action."""
        self.task_log.append({
            "time": time.time(),
            "action": action,
            "object": object_name,
            "target": target_name,
        })

    def get_object(self, name: str) -> Optional[Dict]:
        return self.objects.get(name)

    def get_position(self, name: str) -> Optional[List[float]]:
        obj = self.objects.get(name)
        return obj["position"] if obj else None

    def find_by_color(self, color: str) -> List[str]:
        return [name for name, info in self.objects.items() if info.get("color") == color]

    def find_by_type(self, obj_type: str) -> List[str]:
        return [name for name, info in self.objects.items() if info.get("type") == obj_type]

    def get_moved_objects(self) -> List[str]:
        return [name for name, info in self.objects.items() if info.get("moved", False)]

    def get_state(self) -> Dict:
        return {
            "objects": {name: {
                "position": info["position"],
                "color": info.get("color"),
                "type": info.get("type"),
                "moved": info.get("moved", False),
            } for name, info in self.objects.items()},
            "task_log": self.task_log[-10:],  # Last 10 actions
        }

    # ── Scene Graph / Spatial Relations ────────────────────

    def get_spatial_relation(self, obj_a: str, obj_b: str) -> str:
        """Describe spatial relation between two objects.

        Returns human-readable relation like "left of", "right of", "behind", "in front of", "near".
        """
        pos_a = self.get_position(obj_a)
        pos_b = self.get_position(obj_b)
        if not pos_a or not pos_b:
            return "unknown"

        dx = pos_a[0] - pos_b[0]  # x: front/back (positive = in front)
        dy = pos_a[1] - pos_b[1]  # y: left/right (positive = left)
        dz = pos_a[2] - pos_b[2]  # z: above/below

        # Determine primary relation
        abs_dx, abs_dy, abs_dz = abs(dx), abs(dy), abs(dz)
        max_dim = max(abs_dx, abs_dy, abs_dz)

        if max_dim < 0.05:
            return "near"

        if max_dim == abs_dx:
            return "in front of" if dx > 0 else "behind"
        elif max_dim == abs_dy:
            return "left of" if dy > 0 else "right of"
        else:
            return "above" if dz > 0 else "below"

    def describe_scene(self) -> str:
        """Generate natural language description of the scene with spatial relations."""
        names = list(self.objects.keys())
        if not names:
            return "Empty scene."

        lines = [f"Scene contains {len(names)} objects:"]
        for name, info in self.objects.items():
            pos = info["position"]
            color = info.get("color", "unknown")
            moved = " (moved)" if info.get("moved") else ""
            lines.append(f"  - {name}: {color} at [{pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f}]{moved}")

        # Add spatial relations between pairs
        if len(names) >= 2:
            lines.append("Spatial relations:")
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    rel = self.get_spatial_relation(names[i], names[j])
                    lines.append(f"  - {names[i]} is {rel} {names[j]}")

        return "\n".join(lines)

    def get_scene_graph(self) -> Dict:
        """Return structured scene graph with objects and relations."""
        names = list(self.objects.keys())
        relations = []
        for i in range(len(names)):
            for j in range(len(names)):
                if i != j:
                    rel = self.get_spatial_relation(names[i], names[j])
                    relations.append({
                        "subject": names[i],
                        "relation": rel,
                        "object": names[j],
                    })
        return {
            "objects": {name: {
                "position": info["position"],
                "color": info.get("color"),
                "moved": info.get("moved", False),
            } for name, info in self.objects.items()},
            "relations": relations,
        }

    def _snapshot(self, label: str):
        self.history.append({
            "label": label,
            "time": time.time(),
            "objects": {name: info["position"][:] for name, info in self.objects.items()},
        })

    def _infer_color(self, name: str) -> str:
        name_lower = name.lower()
        if "red" in name_lower or "cup" in name_lower:
            return "red"
        elif "blue" in name_lower or "box" in name_lower:
            return "blue"
        elif "green" in name_lower:
            return "green"
        elif "yellow" in name_lower:
            return "yellow"
        elif "orange" in name_lower:
            return "orange"
        elif "purple" in name_lower:
            return "purple"
        elif "cyan" in name_lower:
            return "cyan"
        elif "white" in name_lower:
            return "white"
        elif "apple" in name_lower:
            return "red"
        elif "bottle" in name_lower:
            return "clear"
        return "unknown"

    def _infer_type(self, name: str) -> str:
        name_lower = name.lower()
        if "cup" in name_lower:
            return "cup"
        elif "box" in name_lower:
            return "box"
        elif "apple" in name_lower:
            return "apple"
        elif "bottle" in name_lower:
            return "bottle"
        return "object"

    def verify_placement(self, object_name: str, target_name: str, proximity_threshold: float = 0.15) -> Dict:
        """Verify if object was placed near target.

        Success requires BOTH:
        - Object moved from its initial position (was actually picked)
        - Object is now within proximity_threshold of target
        """
        obj = self.objects.get(object_name)
        tgt = self.objects.get(target_name)
        if not obj or not tgt:
            return {"success": False, "reasoning": "Object or target not found"}

        obj_pos = obj["position"]
        tgt_pos = tgt["position"]
        distance = sum((obj_pos[i] - tgt_pos[i])**2 for i in range(3))**0.5

        init_pos = obj.get("initial_position", obj_pos)
        moved_from_start = sum((obj_pos[i] - init_pos[i])**2 for i in range(3))**0.5 > 0.05
        near_target = distance < proximity_threshold

        # Success = moved AND near target
        success = moved_from_start and near_target

        if not moved_from_start:
            reasoning = f"Object {object_name} did not move from initial position"
        elif not near_target:
            reasoning = f"Object {object_name} is {distance:.3f}m from target (need <{proximity_threshold}m)"
        else:
            reasoning = f"Object {object_name} placed near {target_name} ({distance:.3f}m)"

        return {
            "success": success,
            "distance_to_target": round(distance, 3),
            "moved_from_start": moved_from_start,
            "near_target": near_target,
            "object_position": [round(x, 3) for x in obj_pos],
            "target_position": [round(x, 3) for x in tgt_pos],
            "reasoning": reasoning,
        }
