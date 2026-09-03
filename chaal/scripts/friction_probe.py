"""Which surface actually sets contact friction, the robot's or the ground's?

`robot.set_friction()` changes the robot's own geoms and leaves the plane at its
default. If Genesis combines a contact pair by taking the larger value, setting
only the robot does nothing at all, and a "low friction" robustness result would
be measuring the baseline twice. This settles it by measurement.
"""
import genesis as gs
import torch

from chaal.env import Go2LocomotionEnv
from chaal.eval import evaluate
from chaal.train import train_config

gs.init(backend=gs.amdgpu, logging_level="warning")
env = Go2LocomotionEnv(num_envs=512)

from rsl_rl.runners import OnPolicyRunner

runner = OnPolicyRunner(env, train_config(1), log_dir=None, device=str(env.device))
runner.load("runs/go2-4096/model_499.pt")
policy = runner.get_inference_policy(device=env.device)

plane = env.scene.entities[0]
MU = 0.2
for tag, robot_mu, plane_mu in [
    ("baseline", 1.0, 1.0),
    ("robot_only", MU, 1.0),
    ("plane_only", 1.0, MU),
    ("both", MU, MU),
]:
    env.robot.set_friction(robot_mu)
    plane.set_friction(plane_mu)
    r = evaluate(env, policy, seconds=10.0)
    print(f"{tag:<12} robot_mu={robot_mu} plane_mu={plane_mu}  "
          f"survival={r['survival_rate']:.3f}  err={r['mean_tracking_error_ms']:.4f}  "
          f"return={r['mean_return']:.1f}", flush=True)

print("CHAAL_DONE")
