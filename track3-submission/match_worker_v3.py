"""Match Worker v2: one robot per Genesis process, with graceful exit.

Fixes:
  - SIGPIPE ignored
  - BrokenPipeError caught
  - Graceful shutdown on MSG_END or socket close
  - 20s match (1000 HL steps at 10Hz)
"""
import argparse, socket, struct, time, sys, os, signal, math
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MSG_STATE = 1
MSG_BALL = 2
MSG_CMD = 3
MSG_END = 4
MSG_WORLD = 5  # Global perception: all robots + ball in one message

DEFAULT_PORT = 9876
N_STEPS = 999999  # No limit — coordinator controls match duration via MSG_END
MAX_MSG_BYTES = 16 * 1024 * 1024  # reject oversized payloads (16 MB)


def pack_state(msg_type, data):
    payload = struct.pack(f'<{len(data)}f', *data) if data else b''
    return struct.pack('<BI', msg_type, len(data)) + payload


def recv_all(sock, n):
    data = b''
    while len(data) < n:
        try:
            chunk = sock.recv(n - len(data))
        except (ConnectionResetError, OSError):
            return None
        if not chunk:
            return None
        data += chunk
    return data


def recv_msg(sock):
    header = recv_all(sock, 5)
    if not header:
        return None, None
    msg_type, length = struct.unpack('<BI', header)
    if length * 4 > MAX_MSG_BYTES:
        print(f'[protocol] refusing oversized message (type={msg_type}, length={length} floats)')
        return None, None
    if length == 0:
        return msg_type, []
    data = recv_all(sock, length * 4)
    if not data:
        return None, None
    return msg_type, struct.unpack(f'<{length}f', data)


class MatchWorker:
    def __init__(self, role, has_ball, port, model_path, init_pos, team_id=0, onnx_path=None):
        self.role = role
        self.has_ball = has_ball
        self.port = port
        self.model_path = model_path
        self.onnx_path = onnx_path
        self.init_pos = init_pos
        self.team_id = team_id
        self.running = False
        self.opp_states = {}  # other robots' positions
        self.all_robot_states = []  # list of {x,y,z,pitch,roll} for all robots
        self.ball_pos = np.array([0.0, 0.0, 0.11])
        self.ball_vel = np.array([0.0, 0.0, 0.0])
        self.collision_push = np.array([0.0, 0.0, 0.0])

    def setup(self):
        import yaml
        import genesis as gs

        gs.init(backend=gs.gpu, logging_level='warning')

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'configs/hierarchical_agent.yaml')) as f:
            cfg = yaml.safe_load(f)
        env_cfg = dict(cfg['env'])
        env_cfg['task'] = 'chase_hl'
        hl_cfg = cfg.get('high_level', {})

        from soccer_env_hierarchical import SoccerEnvHierarchical
        self.env = SoccerEnvHierarchical(
            num_envs=1, env_cfg=env_cfg, obs_cfg=cfg['obs'],
            reward_cfg=cfg['reward'], command_cfg=cfg['command'],
            walk_model_path=hl_cfg.get('walk_model_path'),
            high_level_decimation=hl_cfg.get('decimation', 5),
            show_viewer=False)

        # Override initial position so robot spawns at --init-pos, not default (0,0,0.6)
        import torch as _torch
        self.env.init_base_pos = _torch.tensor(self.init_pos, dtype=_torch.float32, device=self.env.device)
        self.env.init_qpos[0, 0:3] = _torch.tensor(self.init_pos, dtype=_torch.float32, device=self.env.device)

        self.cfg = cfg

        # Three inference paths: ONNX (preferred) → .pt (legacy) → rule
        self.policy = None
        self.onnx_policy = None

        # ONNX is the only inference path (no .pt fallback — per 问题全景梳理)
        if self.onnx_path:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
            from match_3v3.policy import SharedRLPolicy
            self.onnx_policy = SharedRLPolicy(onnx_path=self.onnx_path)
            print(f'[{self.role}] Using ONNX model: {self.onnx_path} (mode={self.onnx_policy.mode})')
        elif self.model_path:
            # .pt path removed — convert to ONNX first, then use --onnx
            print(f'[{self.role}] ERROR: .pt path is deprecated. Use --onnx instead.')
            print(f'[{self.role}] Convert: python export_onnx_mlp.py --model {self.model_path} --output models/chase_policy.onnx')
            sys.exit(1)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect(('localhost', self.port))
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

        while self.running and step < getattr(self, "n_steps", N_STEPS):
            # Receive world state from coordinator
            self.sock.settimeout(120.0)
            try:
                msg_type, data = recv_msg(self.sock)
                if msg_type == MSG_END:
                    print(f'[{self.role}] Received END signal at step {step}')
                    self.running = False
                    break
                elif msg_type is None:
                    print(f'[{self.role}] Connection lost before step {step}')
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
                    self.running = False
                    break
                elif msg_type2 == MSG_CMD and data2:
                    self.collision_push = np.array(data2[:3])
                elif msg_type2 is None:
                    self.running = False
                    break
            except socket.timeout:
                pass  # No new data, use stale state
            self.sock.settimeout(None)

            if not self.running:
                break

            # Compute action — three paths: ONNX → .pt → rule
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

            # Send our state
            agent_pos = self.env.base_pos[0].cpu().numpy()
            agent_pitch = self.env.base_euler[0, 1].item()
            agent_roll = self.env.base_euler[0, 0].item()
            try:
                self.sock.sendall(pack_state(MSG_STATE, [
                    float(agent_pos[0]), float(agent_pos[1]), float(agent_pos[2]),
                    agent_pitch, agent_roll
                ]))
            except (BrokenPipeError, ConnectionResetError, OSError):
                print(f'[{self.role}] Connection lost at step {step}')
                break

            # Send ball state if authority
            if self.has_ball:
                ball_pos = self.env.ball_pos[0].cpu().numpy()
                ball_vel = self.env.ball_vel[0].cpu().numpy()
                try:
                    self.sock.sendall(pack_state(MSG_BALL, [
                        float(ball_pos[0]), float(ball_pos[1]), float(ball_pos[2]),
                        float(ball_vel[0]), float(ball_vel[1]), float(ball_vel[2])
                    ]))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break

            # Log
            if step % 50 == 0:
                ball_d = np.linalg.norm(agent_pos[:2] - self.ball_pos[:2])
                print(f'[{self.role}] step {step}/{N_STEPS}: h={agent_pos[2]:.3f} '
                      f'ball_d={ball_d:.2f} rew={rew.mean().item():.3f}')

        print(f'[{self.role}] Finished after {step} steps')
        try:
            self.sock.close()
        except:
            pass


if __name__ == '__main__':
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    parser = argparse.ArgumentParser()
    parser.add_argument('--role', required=True)
    parser.add_argument('--has-ball', action='store_true')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--model', default=None, help='Path to .pt checkpoint (rsl_rl)')
    parser.add_argument('--onnx', default=None, help='Path to ONNX model (preferred over --model)')
    parser.add_argument('--init-pos', type=float, nargs=3, default=[0, 0, 0.7])
    parser.add_argument('--n-steps', type=int, default=N_STEPS, help='Max HL steps')
    args = parser.parse_args()

    worker = MatchWorker(
        role=args.role, has_ball=args.has_ball, port=args.port,
        model_path=args.model, init_pos=args.init_pos,
        onnx_path=args.onnx)
    worker.n_steps = args.n_steps
    worker.setup()
    worker.run()
