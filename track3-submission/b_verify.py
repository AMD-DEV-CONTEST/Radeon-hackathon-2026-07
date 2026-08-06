"""P0 stability verification for Strategy A rule-walk (bypasses t1_walk.pt).

Runs on the AMD GPU instance. Measures:
  Phase 1 STANCE  (6s, zero command): robot must stay upright, no fall.
  Phase 2 GAIT    (30s, vx=0.5):      robot must walk forward, stay upright, displace >0.3m.

Prints P0_RESULT {...} + VERDICT for automated parsing.
"""
import os, sys, time, json
import numpy as np
import torch

WDIR = '/workspace/amd-physical-ai-soccer'
os.chdir(WDIR)
sys.path.insert(0, WDIR)

import yaml
import genesis as gs
gs.init(backend=gs.gpu, logging_level='error')

with open(os.path.join(WDIR, 'configs/hierarchical_agent.yaml')) as f:
    cfg = yaml.safe_load(f)
env_cfg = dict(cfg['env'])
env_cfg['task'] = 'chase_hl'
env_cfg['use_rule_walk'] = True   # Strategy A: stable deterministic gait
hl_cfg = cfg.get('high_level', {})

from soccer_env_hierarchical import SoccerEnvHierarchical
env = SoccerEnvHierarchical(
    num_envs=1, env_cfg=env_cfg, obs_cfg=cfg['obs'],
    reward_cfg=cfg['reward'], command_cfg=cfg['command'],
    walk_model_path=hl_cfg.get('walk_model_path'),
    high_level_decimation=hl_cfg.get('decimation', 5),
    show_viewer=False)
print('ENV_BUILT_OK use_rule_walk=%s' % env.use_rule_walk, flush=True)

ZERO = torch.zeros((1, 3), dtype=torch.float32, device=env.device)
FWD = torch.tensor([[0.5, 0.0, 0.0]], dtype=torch.float32, device=env.device)

obs = env.reset()

# ── Phase 1: stance stability ──
stance_min_h, stance_max_pitch, stance_max_roll = 99.0, 0.0, 0.0
for s in range(300):
    obs, rew, done, ext = env.step(ZERO)
    h = env.base_pos[0, 2].item()
    p = abs(env.base_euler[0, 1].item())
    r = abs(env.base_euler[0, 0].item())
    stance_min_h = min(stance_min_h, h)
    stance_max_pitch = max(stance_max_pitch, p)
    stance_max_roll = max(stance_max_roll, r)
    if h < 0.3 or p > 30.0 or r > 30.0:
        print('STANCE_FELL step=%d h=%.3f p=%.3f r=%.3f' % (s, h, p, r), flush=True)
        break
print('STANCE done: min_h=%.3f max_pitch=%.3f max_roll=%.3f' %
      (stance_min_h, stance_max_pitch, stance_max_roll), flush=True)

# ── Phase 2: forward gait ──
start = env.base_pos[0, :2].cpu().numpy().copy()
gait_min_h, gait_max_pitch, gait_max_roll, fell = 99.0, 0.0, 0.0, False
for s in range(1500):
    obs, rew, done, ext = env.step(FWD)
    h = env.base_pos[0, 2].item()
    p = abs(env.base_euler[0, 1].item())
    r = abs(env.base_euler[0, 0].item())
    gait_min_h = min(gait_min_h, h)
    gait_max_pitch = max(gait_max_pitch, p)
    gait_max_roll = max(gait_max_roll, r)
    if h < 0.3 or p > 35.0 or r > 35.0:
        print('GAIT_FELL step=%d h=%.3f p=%.3f r=%.3f' % (s, h, p, r), flush=True)
        fell = True
        break
end = env.base_pos[0, :2].cpu().numpy()
disp = float(np.linalg.norm(end - start))
print('GAIT done: disp=%.3f min_h=%.3f max_pitch=%.3f max_roll=%.3f fell=%s' %
      (disp, gait_min_h, gait_max_pitch, gait_max_roll, fell), flush=True)

# ── Verdict ──
stance_ok = (stance_min_h > 0.4) and (stance_max_pitch < 20.0) and (stance_max_roll < 20.0)
gait_ok = (not fell) and (gait_min_h > 0.4) and (gait_max_pitch < 30.0) \
    and (gait_max_roll < 30.0) and (disp > 0.3)
verdict = 'PASS' if (stance_ok and gait_ok) else 'FAIL'
result = {
    'stance_min_h': round(stance_min_h, 3),
    'stance_max_pitch': round(stance_max_pitch, 3),
    'stance_max_roll': round(stance_max_roll, 3),
    'gait_disp': round(disp, 3),
    'gait_min_h': round(gait_min_h, 3),
    'gait_max_pitch': round(gait_max_pitch, 3),
    'gait_max_roll': round(gait_max_roll, 3),
    'stance_ok': stance_ok,
    'gait_ok': gait_ok,
    'VERDICT': verdict,
}
print('P0_RESULT ' + json.dumps(result), flush=True)
