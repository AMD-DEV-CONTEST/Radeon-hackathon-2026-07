"""Prove the environment builds, steps and produces finite rewards."""
import sys, time
import genesis as gs
import torch

from chaal.env import Go2LocomotionEnv

gs.init(backend=gs.amdgpu, logging_level="warning")
n = int(sys.argv[1]) if len(sys.argv) > 1 else 64
env = Go2LocomotionEnv(num_envs=n)
obs, _ = env.reset()
print("obs group keys:", list(obs.keys()), "shape:", tuple(obs["policy"].shape))
assert obs["policy"].shape == (n, env.num_obs), obs["policy"].shape

t0 = time.time()
STEPS = 100
for i in range(STEPS):
    a = torch.zeros((n, env.num_actions), device=env.device)
    obs, rew, done, extras = env.step(a)
dt = time.time() - t0

print(f"stepped {STEPS} x {n} envs in {dt:.2f}s -> {n*STEPS/dt:,.0f} env-steps/s")
print("reward  mean", float(rew.mean()), "finite:", bool(torch.isfinite(rew).all()))
print("obs     finite:", bool(torch.isfinite(obs["policy"]).all()))
print("done    count:", int(done.sum()), "of", n)
print("base z  mean:", float(env.base_pos[:, 2].mean()))
print("time_outs present:", "time_outs" in extras)
print("SMOKE OK")
