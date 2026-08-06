"""Small backend-agnostic helpers for the multi-robot control path."""


def compose_joint_targets(actions, action_scale, default_positions):
    """Map normalized policy actions to absolute joint targets.

    The operands may be NumPy arrays or torch tensors; both implement the
    arithmetic used here. Keeping this calculation pure makes the critical
    policy-to-motor bridge testable without Genesis or a GPU.
    """
    return actions * action_scale + default_positions


def compose_full_joint_targets(actions, action_scale, default_positions, policy_indices):
    """Embed policy-sized actions into the complete motor target vector."""
    policy_defaults = default_positions[policy_indices]
    policy_targets = compose_joint_targets(actions, action_scale, policy_defaults)
    if hasattr(default_positions, "unsqueeze"):
        full_targets = default_positions.unsqueeze(0).expand(actions.shape[0], -1).clone()
    else:
        import numpy as np
        full_targets = np.broadcast_to(default_positions, (actions.shape[0], len(default_positions))).copy()
    full_targets[:, policy_indices] = policy_targets
    return full_targets


def store_robot_actions(action_buffers, robot_idx, actions):
    """Update only one robot's action history and return the stored value."""
    action_buffers[robot_idx] = actions
    return action_buffers[robot_idx]
