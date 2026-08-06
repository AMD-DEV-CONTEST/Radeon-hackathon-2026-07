"""Match Worker v2: one robot per Genesis process, with graceful exit.

Fixes:
  - SIGPIPE ignored
  - BrokenPipeError caught
  - Graceful shutdown on MSG_END or socket close
  - Match lifetime is controlled by MSG_END from the coordinator, or an
    explicitly configured ``--max-steps`` guard.
"""
import argparse, hashlib, socket, time, sys, os, signal, math
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from match_protocol import (
    MSG_STATE, MSG_BALL, MSG_CMD, MSG_END, MSG_WORLD, MSG_HELLO,
    pack_handshake, pack_state, recv_msg, identity_for_role,
    capture_terminal_telemetry,
)

DEFAULT_PORT = 9876


def recv_all(sock, n):
    data = b''
    while len(data) < n:
        try:
            chunk = sock.recv(n - len(data))
        except socket.timeout:
            raise
        except (ConnectionResetError, OSError):
            return None
        if not chunk:
            return None
        data += chunk
    return data


class MatchWorker:
    def __init__(self, role, has_ball, port, model_path, init_pos, team_id=0,
                 onnx_path=None, rule_walk=False, max_steps=None):
        self.role = role
        self.has_ball = has_ball
        self.port = port
        self.model_path = model_path
        self.onnx_path = onnx_path
        self.rule_walk = rule_walk
        if max_steps is not None and max_steps < 1:
            raise ValueError('max_steps must be positive when configured')
        self.max_steps = max_steps
        self.max_steps_reached = False
        self.received_end = False
        self.failed = False
        self.init_pos = init_pos
        self.team_id = team_id
        self.running = False
        self.opp_states = {}  # other robots' positions
        self.all_robot_states = []  # list of {x,y,z,pitch,roll} for all robots
        self.ball_pos = np.array([0.0, 0.0, 0.11])
        self.ball_vel = np.array([0.0, 0.0, 0.0])
        self.collision_push = np.array([0.0, 0.0, 0.0])
        self.walk_model_path = None
        self.model_sha = None
        self.identity = identity_for_role(
            self.role, self.team_id, 'ONNX' if onnx_path else 'Rule', 'unknown',
            self.has_ball)

    @staticmethod
    def _sha256_file(path):
        if not path or not os.path.isfile(path):
            return 'unknown'
        digest = hashlib.sha256()
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def setup(self):
        import yaml
        import genesis as gs

        gs.init(backend=gs.gpu, logging_level='warning')

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'configs/hierarchical_agent.yaml')) as f:
            cfg = yaml.safe_load(f)
        env_cfg = dict(cfg['env'])
        env_cfg['task'] = 'chase_hl'
        env_cfg['use_rule_walk'] = self.rule_walk
        hl_cfg = cfg.get('high_level', {})
        project_dir = os.path.dirname(os.path.abspath(__file__))
        project_walk_model = os.path.join(project_dir, 'models', 'pretrained', 't1_walk.pt')
        configured_walk_model = hl_cfg.get('walk_model_path')
        if configured_walk_model and not os.path.isabs(configured_walk_model):
            configured_walk_model = os.path.join(project_dir, configured_walk_model)
        walk_model_path = (
            project_walk_model if os.path.isfile(project_walk_model)
            else configured_walk_model
        )
        if not self.rule_walk and (not walk_model_path or not os.path.isfile(walk_model_path)):
            raise FileNotFoundError(
                'low-level walk model not found; expected '
                f'{project_walk_model} or configured path {configured_walk_model}'
            )
        self.walk_model_path = walk_model_path
        controller = 'ONNX' if self.onnx_path else 'Rule'
        model_path_for_identity = self.onnx_path or walk_model_path
        model_sha = self._sha256_file(model_path_for_identity)
        if self.rule_walk and not self.onnx_path:
            model_sha = hashlib.sha256(b'rule-walk').hexdigest()
        self.model_sha = model_sha

        from soccer_env_hierarchical import SoccerEnvHierarchical
        self.env = SoccerEnvHierarchical(
            num_envs=1, env_cfg=env_cfg, obs_cfg=cfg['obs'],
            reward_cfg=cfg['reward'], command_cfg=cfg['command'],
            walk_model_path=walk_model_path,
            high_level_decimation=hl_cfg.get('decimation', 5),
            show_viewer=False)

        # Override initial position so robot spawns at --init-pos, not default (0,0,0.6)
        import torch as _torch
        self.env.init_base_pos = _torch.tensor(self.init_pos, dtype=_torch.float32, device=self.env.device)
        self.env.init_qpos[0, 0:3] = _torch.tensor(self.init_pos, dtype=_torch.float32, device=self.env.device)

        self.cfg = cfg

        # Inference paths: ONNX policy when provided, otherwise deterministic rule.
        self.policy = None
        self.onnx_policy = None

        # ONNX is the only inference path (no .pt fallback — per 问题全景梳理)
        if self.onnx_path:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
            from match_3v3.policy import SharedRLPolicy
            self.onnx_policy = SharedRLPolicy(onnx_path=self.onnx_path)
            if not self.onnx_policy.onnx_loaded or self.onnx_policy.mode != 'onnx_vs_rule':
                raise RuntimeError(
                    'ONNX requested but SharedRLPolicy did not load a real ONNX session'
                )
            print(f'[{self.role}] Using ONNX model: {self.onnx_path} (mode={self.onnx_policy.mode})')
        elif self.model_path:
            # .pt path removed — convert to ONNX first, then use --onnx
            print(f'[{self.role}] ERROR: .pt path is deprecated. Use --onnx instead.')
            print(f'[{self.role}] Convert: python export_onnx_mlp.py --model {self.model_path} --output models/chase_policy.onnx')
            sys.exit(1)

        # Declare identity only after the requested controller has actually
        # loaded; this prevents reporting ONNX while silently using RulePolicy.
        self.identity = identity_for_role(
            self.role, self.team_id, controller, model_sha, self.has_ball)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect(('localhost', self.port))
        self.sock.sendall(pack_handshake(self.identity))
        print(f'[{self.role}] Connected to coordinator')

    def run(self):
        self.running = True
        obs = self.env.reset()
        # Force robot to spawn at init_pos (init_qpos override alone doesn't work in Genesis)
        import torch as _torch
        pos = _torch.tensor([self.init_pos], dtype=_torch.float32, device=self.env.device)
        self.env.robot.set_pos(pos)
        self.env.base_pos[0, :3] = pos[0]
        self.env._read_state()
        step = 0

        # The coordinator owns match lifetime and sends MSG_END when its
        # duration elapses. ``max_steps`` is an optional local safety/CI
        # guard; there is deliberately no implicit fixed step limit here.
        while self.running and (self.max_steps is None or step < self.max_steps):
            # Receive world state from coordinator
            self.sock.settimeout(120.0)
            try:
                msg_type, data = recv_msg(self.sock)
                if msg_type == MSG_END:
                    print(f'[{self.role}] Received END signal at step {step}')
                    self.received_end = True
                    self.running = False
                    break
                elif msg_type is None:
                    print(f'[{self.role}] Connection lost before step {step}')
                    self.failed = True
                    self.running = False
                    break
                elif msg_type == MSG_WORLD and data:
                    # Parse world state: [n_robots * 5 (x,y,z,pitch,roll)] + [ball 6]
                    n_robots = (len(data) - 6) // 5
                    self.all_robot_states = []
                    for i in range(n_robots):
                        base = i * 5
                        self.all_robot_states.append({
                            'x': data[base], 'y': data[base+1], 'z': data[base+2],
                            'pitch': data[base+3], 'roll': data[base+4]
                        })
                    # Ball is last 6 floats
                    ball_start = n_robots * 5
                    if not self.has_ball:
                        self.ball_pos = np.array(data[ball_start:ball_start+3])
                        self.ball_vel = np.array(data[ball_start+3:ball_start+6])
                elif msg_type == MSG_CMD and data:
                    self.collision_push = np.array(data[:3])

                # Read collision push (if sent separately)
                msg_type2, data2 = recv_msg(self.sock)
                if msg_type2 == MSG_END:
                    self.received_end = True
                    self.running = False
                    break
                elif msg_type2 == MSG_CMD and data2:
                    self.collision_push = np.array(data2[:3])
                elif msg_type2 is None:
                    self.failed = True
                    self.running = False
                    break
            except socket.timeout:
                pass  # No new data, use stale state
            self.sock.settimeout(None)

            if not self.running:
                break

            # Compute action — ONNX policy when configured, otherwise rule.
            if self.onnx_policy:
                # ONNX Runtime inference: build PlayerState + BallState from env
                from match_3v3.scene import PlayerState, BallState, Team, Role
                robot_pos = self.env.base_pos[0].cpu().numpy()
                robot_quat = self.env.base_quat[0].cpu().numpy()
                robot_vel = self.env.filtered_lin_vel[0].cpu().numpy()
                ball_pos = self.ball_pos
                ball_vel = self.ball_vel

                # Determine team from role (A = LEFT attacks +x, B = RIGHT attacks -x)
                is_team_a = self.role.startswith('A')
                team = Team.LEFT if is_team_a else Team.RIGHT

                player = PlayerState(
                    team=team, robot_idx=0, role=Role.ATTACKER,
                    pos=robot_pos, quat=robot_quat, vel=robot_vel,
                )
                ball = BallState(pos=ball_pos, vel=ball_vel)

                # Build teammate/opponent position lists from all_robot_states
                # all_robot_states[0..2] = Team A, [3..5] = Team B
                # Only pass teammates/opponents if ONNX model expects 24-dim input
                teammates = None
                opponents = None
                if self.onnx_policy and self.onnx_policy.session is not None:
                    # Check ONNX input dimension
                    input_shape = self.onnx_policy.session.get_inputs()[0].shape
                    onnx_dim = input_shape[-1] if input_shape else 19
                    if onnx_dim == 24 and len(self.all_robot_states) >= 6:
                        my_indices = range(0, 3) if is_team_a else range(3, 6)
                        opp_indices = range(3, 6) if is_team_a else range(0, 3)
                        teammates = []
                        opponents = []
                        for i in my_indices:
                            s = self.all_robot_states[i]
                            teammates.append(np.array([s['x'], s['y'], s['z']]))
                        for i in opp_indices:
                            s = self.all_robot_states[i]
                            opponents.append(np.array([s['x'], s['y'], s['z']]))

                action_result = self.onnx_policy.compute(player, ball, teammates, opponents)
                action = torch.tensor([action_result.velocity_cmd],
                                      dtype=torch.float32, device=self.env.device)

            elif self.policy:
                # .pt path removed — ONNX only
                action = torch.zeros((1, 3), dtype=torch.float32, device=self.env.device)
            else:
                # Rule-based: chase ball
                robot_pos = self.env.base_pos[0, :3].cpu().numpy()
                ball_rel = self.ball_pos - robot_pos
                dist = np.linalg.norm(ball_rel[:2])
                if dist > 0.05:
                    direction = ball_rel[:2] / dist
                    action = torch.tensor([[
                        np.clip(direction[0] * 0.2, -0.2, 0.2),
                        np.clip(direction[1] * 0.2, -0.2, 0.2),
                        np.clip(np.arctan2(ball_rel[1], ball_rel[0]) * 0.1, -0.2, 0.2),
                    ]], dtype=torch.float32, device=self.env.device)
                else:
                    action = torch.zeros((1, 3), dtype=torch.float32, device=self.env.device)

            # Step environment
            obs, rew, done, extras = self.env.step(action)
            step += 1

            # Capture terminal values before the environment resets a finished
            # episode.  Older environments may not expose these extras, so the
            # live state remains the compatibility fallback.
            telemetry = capture_terminal_telemetry(
                extras,
                self.env.base_pos[0].cpu().numpy(),
                self.env.base_euler[0].cpu().numpy(),
                self.env.ball_pos[0].cpu().numpy(),
                self.env.ball_vel[0].cpu().numpy(),
            )
            fallen = telemetry['fallen']
            scored = telemetry['scored']
            agent_pos = np.asarray(telemetry['base_pos'], dtype=np.float32)
            agent_euler = np.asarray(telemetry['base_euler'], dtype=np.float32)

            # Send our state
            agent_pitch = float(agent_euler[1]) if len(agent_euler) > 1 else float(self.env.base_euler[0, 1].item())
            agent_roll = float(agent_euler[0]) if len(agent_euler) > 0 else float(self.env.base_euler[0, 0].item())
            try:
                self.sock.sendall(pack_state(MSG_STATE, [
                    float(agent_pos[0]), float(agent_pos[1]), float(agent_pos[2]),
                    agent_pitch, agent_roll, float(fallen), float(scored)
                ]))
            except (BrokenPipeError, ConnectionResetError, OSError):
                print(f'[{self.role}] Connection lost at step {step}')
                self.failed = True
                self.running = False
                break

            # Send ball state if authority
            if self.has_ball:
                ball_pos = np.asarray(telemetry['ball_pos'], dtype=np.float32)
                ball_vel = np.asarray(telemetry['ball_vel'], dtype=np.float32)
                try:
                    self.sock.sendall(pack_state(MSG_BALL, [
                        float(ball_pos[0]), float(ball_pos[1]), float(ball_pos[2]),
                        float(ball_vel[0]), float(ball_vel[1]), float(ball_vel[2])
                    ]))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    self.failed = True
                    self.running = False
                    break

            # Log
            if step % 50 == 0:
                ball_d = np.linalg.norm(agent_pos[:2] - self.ball_pos[:2])
                limit = self.max_steps if self.max_steps is not None else 'MSG_END'
                print(f'[{self.role}] step {step}/{limit}: h={agent_pos[2]:.3f} '
                      f'ball_d={ball_d:.2f} rew={rew.mean().item():.3f}')

        # Reaching the local guard is intentionally distinguishable from a
        # coordinator MSG_END.  The launcher may explicitly allow this in a
        # bounded test run, but a normal match must be considered incomplete.
        self.max_steps_reached = (
            self.max_steps is not None and step >= self.max_steps and self.running
        )
        if self.failed:
            print(f'[{self.role}] Incomplete: connection lost before MSG_END')
        elif self.max_steps_reached:
            print(f'[{self.role}] Incomplete: max_steps={self.max_steps} reached '
                  'before MSG_END')
        else:
            print(f'[{self.role}] Finished after {step} steps')
        try:
            self.sock.close()
        except:
            pass
        if self.failed:
            return 1
        return 3 if self.max_steps_reached else 0


if __name__ == '__main__':
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    parser = argparse.ArgumentParser()
    parser.add_argument('--role', required=True)
    parser.add_argument('--has-ball', action='store_true')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--model', default=None,
                        help='Deprecated .pt checkpoint argument; use --onnx')
    parser.add_argument('--onnx', default=None, help='Path to a .onnx policy model')
    parser.add_argument('--max-steps', type=int, default=None,
                        help='Optional local step limit; default is coordinator MSG_END')
    parser.add_argument('--init-pos', type=float, nargs=3, default=[0, 0, 0.7])
    parser.add_argument('--rule-walk', dest='rule_walk', action='store_true', default=False,
                        help='Diagnostic only: use deterministic rule-walk instead of pretrained t1_walk.pt')
    parser.add_argument('--no-rule-walk', dest='rule_walk', action='store_false',
                        help='Use the pretrained t1_walk.pt low-level walk model (default)')
    args = parser.parse_args()

    if args.max_steps is not None and args.max_steps < 1:
        parser.error('--max-steps must be a positive integer')
    if args.onnx is not None:
        if not args.onnx.endswith('.onnx'):
            parser.error('--onnx must point to a .onnx file')
        if not os.path.isfile(args.onnx):
            parser.error(f'ONNX model not found: {args.onnx}')

    worker = MatchWorker(
        role=args.role, has_ball=args.has_ball, port=args.port,
        model_path=args.model, init_pos=args.init_pos,
        onnx_path=args.onnx, rule_walk=args.rule_walk, max_steps=args.max_steps)
    worker.setup()
    sys.exit(worker.run())
