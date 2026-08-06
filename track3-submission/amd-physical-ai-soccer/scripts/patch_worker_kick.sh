#!/bin/bash
# Patch match_worker.py to add kick behavior for ONNX workers
# Creates match_worker_v3.py with kick logic added after ONNX compute
set +e

cd /workspace/radeon-repo

# Create patched version
cp match_worker.py match_worker_v3.py

# Use python to patch the file
/opt/venv/bin/python3 << 'PATCHEOF'
import re

with open('match_worker_v3.py', 'r') as f:
    content = f.read()

# Find the line with "action_result = self.onnx_policy.compute" and add kick logic after the action tensor creation
old_block = """                action_result = self.onnx_policy.compute(player, ball, teammates, opponents)
                action = torch.tensor([action_result.velocity_cmd],
                                      dtype=torch.float32, device=self.env.device)"""

new_block = """                action_result = self.onnx_policy.compute(player, ball, teammates, opponents)
                vel_cmd = action_result.velocity_cmd.copy()

                # Kick behavior: if close to ball, dash toward opponent goal
                robot_pos_np = self.env.base_pos[0, :3].cpu().numpy()
                ball_rel = self.ball_pos - robot_pos_np
                dist_to_ball = float(np.linalg.norm(ball_rel[:2]))

                if dist_to_ball < 0.4:
                    # Determine attack direction (Team A attacks +x, Team B attacks -x)
                    is_team_a = self.role.startswith('A')
                    attack_x = 7.0 if is_team_a else -7.0
                    # Direction from ball to attack goal
                    goal_rel = np.array([attack_x - self.ball_pos[0], -self.ball_pos[1]])
                    goal_dist = np.linalg.norm(goal_rel)
                    if goal_dist > 0.01:
                        goal_dir = goal_rel / goal_dist
                        # Boost velocity toward goal (dash/kick)
                        vel_cmd[0] = goal_dir[0] * 0.8  # max speed boost
                        vel_cmd[1] = goal_dir[1] * 0.8

                action = torch.tensor([vel_cmd],
                                      dtype=torch.float32, device=self.env.device)"""

if old_block in content:
    content = content.replace(old_block, new_block)
    print("PATCHED: kick behavior added to ONNX path")
else:
    print("WARNING: Could not find target block to patch")
    # Try a more flexible approach
    pattern = r'action_result = self\.onnx_policy\.compute\(player, ball, teammates, opponents\)\s*\n\s*action = torch\.tensor\(\[action_result\.velocity_cmd\],\s*\n\s*dtype=torch\.float32, device=self\.env\.device\)'
    replacement = new_block
    new_content = re.sub(pattern, replacement, content)
    if new_content != content:
        content = new_content
        print("PATCHED (regex fallback): kick behavior added")
    else:
        print("ERROR: Could not patch match_worker_v3.py")

with open('match_worker_v3.py', 'w') as f:
    f.write(content)

print("match_worker_v3.py created successfully")
PATCHEOF

echo "=== PATCH DONE ==="
# Verify the patch
grep -n "kick\|dash\|goal_dir\|dist_to_ball" match_worker_v3.py | head -10
