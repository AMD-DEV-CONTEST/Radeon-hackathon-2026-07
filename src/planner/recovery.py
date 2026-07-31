"""
Task Recovery — Detect failures and replan.

Flow:
    Action → Observe → Detect Failure → Replan → Retry

Uses GraspEnv (not the deleted ManipulationPipeline / RobotPrimitives).
"""
import time
from typing import Dict, List


class FailureDetector:
    """Detect failures from scene state changes."""

    def __init__(self, scene_memory):
        self.memory = scene_memory
        self.failure_history = []

    def check_grasp_failure(self, object_name: str, pre_pos: List[float], post_pos: List[float]) -> Dict:
        if pre_pos is None or post_pos is None:
            return {"detected": False, "reason": "missing position data"}

        moved = sum(abs(post_pos[i] - pre_pos[i]) for i in range(3)) > 0.005
        return {
            "detected": not moved,
            "type": "grasp_failure",
            "reason": f"Object {object_name} did not move after grasp attempt",
            "pre_pos": pre_pos,
            "post_pos": post_pos,
        }

    def check_drop_failure(self, object_name: str, pre_pos: List[float], post_pos: List[float]) -> Dict:
        if pre_pos is None or post_pos is None:
            return {"detected": False, "reason": "missing position data"}

        z_dropped = pre_pos[2] - post_pos[2] > 0.05
        return {
            "detected": z_dropped,
            "type": "drop_failure",
            "reason": f"Object {object_name} z decreased by {pre_pos[2] - post_pos[2]:.3f}m",
            "pre_pos": pre_pos,
            "post_pos": post_pos,
        }

    def check_position_drift(self, object_name: str, target_pos: List[float], actual_pos: List[float], threshold: float = 0.1) -> Dict:
        if target_pos is None or actual_pos is None:
            return {"detected": False, "reason": "missing position data"}

        distance = sum((actual_pos[i] - target_pos[i])**2 for i in range(3))**0.5
        return {
            "detected": distance > threshold,
            "type": "position_drift",
            "reason": f"Object {object_name} is {distance:.3f}m from target (threshold: {threshold}m)",
            "distance": distance,
            "threshold": threshold,
        }

    def check_ik_failure(self, object_name: str, target_pos: List[float], actual_pos: List[float], threshold: float = 0.05) -> Dict:
        """Check if IK solution resulted in significant error."""
        if target_pos is None or actual_pos is None:
            return {"detected": False, "reason": "missing position data"}

        distance = sum((actual_pos[i] - target_pos[i])**2 for i in range(3))**0.5
        return {
            "detected": distance > threshold,
            "type": "ik_failure",
            "reason": f"IK error for {object_name}: {distance:.3f}m (threshold: {threshold}m)",
            "distance": distance,
            "threshold": threshold,
        }

    def check_convergence_failure(self, object_name: str, reached: bool) -> Dict:
        """Check if PD control converged to target."""
        return {
            "detected": not reached,
            "type": "convergence_failure",
            "reason": f"PD control did not converge for {object_name}",
        }

    def check_path_planning_failure(self, object_name: str, path_valid: bool) -> Dict:
        """Check if path planning succeeded."""
        return {
            "detected": not path_valid,
            "type": "path_planning_failure",
            "reason": f"Path planning failed for {object_name}",
        }

    def check_weld_constraint_failure(self, object_name: str, weld_success: bool) -> Dict:
        """Check if weld constraint was successfully added/removed."""
        return {
            "detected": not weld_success,
            "type": "weld_constraint_failure",
            "reason": f"Weld constraint operation failed for {object_name}",
        }

    def record_failure(self, failure: Dict):
        self.failure_history.append({"time": time.time(), **failure})

    def should_abort(self) -> bool:
        return len(self.failure_history) >= 3

    def get_failure_count(self) -> int:
        return len(self.failure_history)


class Replanner:
    """Replan after failure detection — produces actions for GraspEnv."""

    def __init__(self):
        self.retry_strategies = {
            "grasp_failure": self._retry_grasp,
            "drop_failure": self._retry_drop,
            "position_drift": self._retry_drift,
            "ik_failure": self._retry_ik,
            "convergence_failure": self._retry_convergence,
            "path_planning_failure": self._retry_path_planning,
            "weld_constraint_failure": self._retry_weld,
            "execution_exception": self._retry_exception,
            "action_failure": self._retry_generic,
        }

    def replan(self, failed_action: Dict, failure: Dict, scene_memory) -> List[Dict]:
        failure_type = failure.get("type", "unknown")
        strategy = self.retry_strategies.get(failure_type, self._generic_retry)
        return strategy(failed_action, failure, scene_memory)

    def _retry_grasp(self, action: Dict, failure: Dict, memory) -> List[Dict]:
        """Replan grasp: move to safe height, then re-approach with offset.

        Strategy: lift arm to safe z → approach object from slightly
        different xy position (offset by 1cm) → re-attempt pick.
        """
        obj_name = action.get("object", action.get("pick", ""))
        return [
            {"action": "move_above", "object": obj_name,
             "description": f"Move to safe height above {obj_name}"},
            {"action": "pick", "object": obj_name,
             "approach": "offset_retry",
             "offset_xy": [0.01, -0.01],
             "description": f"Re-approach {obj_name} with 1cm xy offset"},
        ]

    def _retry_drop(self, action: Dict, failure: Dict, memory) -> List[Dict]:
        """Replan drop: move to safe height, re-grasp, then place with offset."""
        obj_name = action.get("object", "")
        tgt = action.get("target", action.get("place", ""))
        return [
            {"action": "move_above", "object": obj_name,
             "description": f"Move to safe height above {obj_name}"},
            {"action": "pick", "object": obj_name,
             "approach": "offset_retry",
             "offset_xy": [0.01, -0.01],
             "description": "Re-grasp dropped object with offset"},
            {"action": "place", "object": obj_name, "target": tgt,
             "description": "Place at target"},
        ]

    def _retry_drift(self, action: Dict, failure: Dict, memory) -> List[Dict]:
        """Replan drift: re-grasp with offset and place with precision."""
        obj_name = action.get("object", "")
        tgt = action.get("target", action.get("place", ""))
        return [
            {"action": "move_above", "object": obj_name,
             "description": f"Move to safe height above {obj_name}"},
            {"action": "pick", "object": obj_name,
             "approach": "offset_retry",
             "offset_xy": [-0.01, 0.01],
             "description": "Re-grasp with opposite offset"},
            {"action": "place", "object": obj_name, "target": tgt,
             "description": "Place at target (precision retry)"},
        ]

    def _retry_ik(self, action: Dict, failure: Dict, memory) -> List[Dict]:
        """Replan for IK failure: move to safe height and retry with offset."""
        obj_name = action.get("object", action.get("pick", ""))
        return [
            {"action": "move_above", "object": obj_name, "height": 0.30,
             "description": f"Move to safe height above {obj_name} (IK retry)"},
            {**action, "approach": "offset_retry", "offset_xy": [0.02, -0.02],
             "description": f"Retry {action.get('action', '')} with 2cm offset"},
        ]

    def _retry_convergence(self, action: Dict, failure: Dict, memory) -> List[Dict]:
        """Replan for convergence failure: wait longer and retry."""
        obj_name = action.get("object", action.get("pick", ""))
        return [
            {"action": "wait", "steps": 100, "description": "Wait for convergence"},
            {**action, "description": f"Retry {action.get('action', '')} after wait"},
        ]

    def _retry_path_planning(self, action: Dict, failure: Dict, memory) -> List[Dict]:
        """Replan for path planning failure: try different approach."""
        obj_name = action.get("object", action.get("pick", ""))
        return [
            {"action": "move_above", "object": obj_name, "height": 0.35,
             "description": f"Move to higher safe height above {obj_name}"},
            {**action, "approach": "direct", "description": f"Direct approach to {obj_name}"},
        ]

    def _retry_weld(self, action: Dict, failure: Dict, memory) -> List[Dict]:
        """Replan for weld constraint failure: reset and retry."""
        obj_name = action.get("object", action.get("pick", ""))
        return [
            {"action": "move_above", "object": obj_name, "height": 0.25,
             "description": f"Move to safe height above {obj_name}"},
            {"action": "wait", "steps": 50, "description": "Wait for physics to settle"},
            {**action, "description": f"Retry {action.get('action', '')} after reset"},
        ]

    def _retry_exception(self, action: Dict, failure: Dict, memory) -> List[Dict]:
        """Replan for execution exception: reset and retry."""
        obj_name = action.get("object", action.get("pick", ""))
        return [
            {"action": "move_above", "object": obj_name, "height": 0.25,
             "description": f"Move to safe height above {obj_name}"},
            {"action": "wait", "steps": 100, "description": "Wait for recovery"},
            {**action, "description": f"Retry {action.get('action', '')} after exception"},
        ]

    def _retry_generic(self, action: Dict, failure: Dict, memory) -> List[Dict]:
        """Generic retry strategy."""
        return [action]

    def _generic_retry(self, action: Dict, failure: Dict, memory) -> List[Dict]:
        return [action]


class RecoveryManager:
    """Orchestrates failure detection and replanning for GraspEnv."""

    def __init__(self, scene_memory):
        self.detector = FailureDetector(scene_memory)
        self.replanner = Replanner()
        self.max_retries = 2

    def execute_with_recovery(self, pipeline, action: Dict, scene_objects: Dict,
                              target_pos=None) -> Dict:
        """Execute pick/place via ManipulationPipeline with retry on failure.

        pipeline: ManipulationPipeline instance
        action: {"action": "pick"|"place", "object": ..., "target": ...}
        scene_objects: {name: entity} for position checks
        target_pos: [x,y,z] for place actions
        """
        action_type = action["action"]
        obj_name = action.get("object", "")

        # Validate object exists
        if obj_name and obj_name not in scene_objects:
            return {"success": False, "reason": f"Object {obj_name} not found in scene", "attempts": 0}

        # Validate target position for place actions
        if action_type == "place" and target_pos is not None:
            if len(target_pos) < 3 or target_pos[2] < 0:
                return {"success": False, "reason": f"Invalid target position: {target_pos}", "attempts": 0}

        for attempt in range(self.max_retries + 1):
            pre_pos = self._obj_pos(scene_objects, obj_name)

            # Execute via GraspEnv with exception handling
            try:
                if action_type == "pick":
                    success = pipeline.suction_pick(obj_name)
                elif action_type == "place":
                    if target_pos is None:
                        return {"success": False, "reason": "no target_pos for place"}
                    err = pipeline.suction_place(obj_name, target_pos)
                    success = err < 0.10
                else:
                    # Delegate to execute_action (handles move_above, wait, etc.)
                    result = pipeline.execute_action(action)
                    success = result.get("ok", False)
            except Exception as e:
                # Capture any exceptions during execution
                failure = {
                    "detected": True,
                    "type": "execution_exception",
                    "reason": f"Exception during {action_type}: {str(e)}",
                    "exception": str(e),
                }
                self.detector.record_failure(failure)
                if self.detector.should_abort():
                    return {"success": False, "reason": "Too many failures", "attempts": attempt + 1}
                continue

            post_pos = self._obj_pos(scene_objects, obj_name)

            # Detect failure - check multiple failure modes
            failure = None
            if action_type == "pick":
                # Check grasp failure (object didn't move)
                failure = self.detector.check_grasp_failure(obj_name, pre_pos, post_pos)
                # Also check if object fell (z decreased)
                if not failure["detected"]:
                    drop_failure = self.detector.check_drop_failure(obj_name, pre_pos, post_pos)
                    if drop_failure["detected"]:
                        failure = drop_failure
            elif action_type == "place":
                # Check drop failure (object z decreased)
                failure = self.detector.check_drop_failure(obj_name, pre_pos, post_pos)
                # Also check position drift if we have target
                if not failure["detected"] and target_pos is not None:
                    drift_failure = self.detector.check_position_drift(obj_name, target_pos, post_pos)
                    if drift_failure["detected"]:
                        failure = drift_failure
            else:
                # For other actions, check if execution succeeded
                if not success:
                    failure = {
                        "detected": True,
                        "type": "action_failure",
                        "reason": f"Action {action_type} failed",
                    }

            if failure is None or not failure["detected"]:
                return {"success": True, "attempts": attempt + 1}

            self.detector.record_failure(failure)

            if self.detector.should_abort():
                return {"success": False, "reason": "Too many failures", "attempts": attempt + 1}

            new_plan = self.replanner.replan(action, failure, self.detector.memory)
            step_ok = True
            for new_action in new_plan:
                sub = self.execute_with_recovery(
                    pipeline, new_action, scene_objects, target_pos)
                if not sub.get("success"):
                    step_ok = False
                    break
            if step_ok:
                return {"success": True, "attempts": attempt + 1,
                        "replanned": True}

        return {"success": False, "reason": "Max retries exceeded", "attempts": self.max_retries + 1}

    def _obj_pos(self, scene_objects, name):
        if not name or name not in scene_objects:
            return None
        return scene_objects[name].get_pos().cpu().numpy().tolist()
