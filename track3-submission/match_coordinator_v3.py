#!/usr/bin/env python3
"""Match Coordinator v3: with disturbance support.

Adds:
  --disturbance flag: enables random push forces every N steps
  --disturbance-interval: steps between push (default 200)
  --disturbance-force: max force in Newtons (default 5.0)
  --ball-random: randomize ball initial position
  --seed: random seed for reproducibility

Usage:
  python match_coordinator_v3.py --port 9893 --n-teams 2 --duration 25.0 --disturbance
"""
import argparse, socket, struct, json, threading, time, signal, os, random
from datetime import datetime

MSG_STATE = 1
MSG_BALL = 2
MSG_CMD = 3
MSG_END = 4
MSG_WORLD = 5

DEFAULT_PORT = 9876
MATCH_DURATION = 20.0
SYNC_HZ = 50
MAX_MSG_BYTES = 16 * 1024 * 1024  # reject oversized payloads (16 MB)
COLLISION_DIST = 0.3


def pack_state(msg_type, data):
    payload = struct.pack(f'<{len(data)}f', *data) if data else b''
    return struct.pack('<BI', msg_type, len(data)) + payload


def recv_all(sock, n):
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
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


class MatchCoordinatorV3:
    def __init__(self, port=DEFAULT_PORT, n_teams=2, log_dir='match_logs',
                 disturbance=False, dist_interval=200, dist_force=5.0,
                 ball_random=False, seed=42):
        self.port = port
        self.n_teams = n_teams
        self.running = False
        self.clients = {}
        self.states = {}
        self.ball = {'x': 0, 'y': 0, 'z': 0.11, 'vx': 0, 'vy': 0, 'vz': 0}
        self.lock = threading.Lock()
        self.log_dir = log_dir
        self.match_log = []
        self.start_time = None

        # Disturbance config
        self.disturbance = disturbance
        self.dist_interval = dist_interval
        self.dist_force = dist_force
        self.ball_random = ball_random
        self.rng = random.Random(seed)

        if ball_random:
            bx = self.rng.uniform(-2.0, 2.0)
            by = self.rng.uniform(-1.0, 1.0)
            self.ball = {'x': bx, 'y': by, 'z': 0.11, 'vx': 0, 'vy': 0, 'vz': 0}
            print(f'[Coord] Ball randomized to ({bx:.2f}, {by:.2f})')

        os.makedirs(log_dir, exist_ok=True)

    def run(self):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        self.running = True
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('localhost', self.port))
        server.listen(self.n_teams * 3 + 2)
        print(f'[Coord] Listening on port {self.port}, expecting up to {self.n_teams*3} clients')
        if self.disturbance:
            print(f'[Coord] Disturbance ENABLED: interval={self.dist_interval}, force={self.dist_force}N')

        expected = 2 if self.n_teams <= 1 else self.n_teams * 3
        accept_deadline = time.time() + 600
        connected = 0
        while connected < expected and time.time() < accept_deadline:
            remaining = accept_deadline - time.time()
            if remaining <= 0:
                break
            server.settimeout(remaining)
            try:
                conn, addr = server.accept()
            except socket.timeout:
                break
            name = f'client_{connected}'
            self.clients[name] = conn
            self.states[name] = {'x': 0, 'y': 0, 'z': 0.7, 'pitch': 0, 'roll': 0}
            print(f'[Coord] {name} connected from {addr} ({connected+1}/{expected})')
            threading.Thread(target=self._handle_client, args=(conn, name), daemon=True).start()
            connected += 1

        if connected < expected:
            print(f'[Coord] Warning: only {connected}/{expected} clients connected')
        print(f'[Coord] All clients connected, starting match')

        server.settimeout(None)
        self.start_time = time.time()

        step_count = 0

        while self.running and time.time() - self.start_time < MATCH_DURATION:
            elapsed = time.time() - self.start_time

            with self.lock:
                states_snapshot = {k: dict(v) for k, v in self.states.items()}
                ball_snapshot = dict(self.ball)

            client_names = list(self.clients.keys())
            collisions = []
            for i in range(len(client_names)):
                for j in range(i + 1, len(client_names)):
                    a = states_snapshot.get(client_names[i], {})
                    b = states_snapshot.get(client_names[j], {})
                    if 'x' in a and 'x' in b:
                        dx = a['x'] - b['x']
                        dy = a['y'] - b['y']
                        dist = (dx**2 + dy**2) ** 0.5
                        if dist < COLLISION_DIST and dist > 0.01:
                            collisions.append((client_names[i], client_names[j], dist, dx, dy))

            # Check if disturbance push should be applied this step
            apply_disturbance = (self.disturbance and 
                                 step_count > 0 and 
                                 step_count % self.dist_interval == 0)
            if apply_disturbance:
                print(f'[Coord] Injecting disturbance at step {step_count} (t={elapsed:.1f}s)')

            client_names = list(self.clients.keys())
            n_robots = len(client_names)

            world_data = []
            for cn in client_names:
                s = states_snapshot.get(cn, {})
                world_data.extend([
                    s.get('x', 0), s.get('y', 0), s.get('z', 0.7),
                    s.get('pitch', 0), s.get('roll', 0)
                ])
            world_data.extend([
                ball_snapshot['x'], ball_snapshot['y'], ball_snapshot['z'],
                ball_snapshot['vx'], ball_snapshot['vy'], ball_snapshot['vz']
            ])

            for name, conn in self.clients.items():
                self._safe_send(conn, MSG_WORLD, world_data)

                # Compute push: collision + disturbance
                push = [0, 0, 0]
                for c in collisions:
                    if name == c[0]:
                        push[0] = c[3] / c[2] * 0.1
                        push[1] = c[4] / c[2] * 0.1
                    elif name == c[1]:
                        push[0] = -c[3] / c[2] * 0.1
                        push[1] = -c[4] / c[2] * 0.1

                # Add disturbance push
                if apply_disturbance:
                    angle = self.rng.uniform(0, 2 * 3.14159)
                    push[0] += self.rng.uniform(0, self.dist_force) * 0.1 * __import__('math').cos(angle)
                    push[1] += self.rng.uniform(0, self.dist_force) * 0.1 * __import__('math').sin(angle)

                self._safe_send(conn, MSG_CMD, push)

            log_entry = {
                't': round(elapsed, 3),
                'ball': {k: round(v, 4) for k, v in ball_snapshot.items()},
                'robots': {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in states_snapshot.items()},
                'collisions': len(collisions),
            }
            if apply_disturbance:
                log_entry['disturbance'] = True
            self.match_log.append(log_entry)
            step_count += 1

            time.sleep(1.0 / SYNC_HZ)

        for conn in self.clients.values():
            self._safe_send(conn, MSG_END, [])

        elapsed = time.time() - self.start_time if self.start_time else 0
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = os.path.join(self.log_dir, f'match_{timestamp}.json')
        with open(log_path, 'w') as f:
            json.dump({
                'duration': round(elapsed, 2),
                'n_clients': len(self.clients),
                'sync_hz': SYNC_HZ,
                'steps': len(self.match_log),
                'disturbance': self.disturbance,
                'ball_random': self.ball_random,
                'log': self.match_log,
            }, f, indent=2)

        print(f'[Coord] Match ended after {elapsed:.1f}s, {len(self.match_log)} steps logged')
        print(f'[Coord] Log saved to {log_path}')
        self.running = False

        for conn in self.clients.values():
            try:
                conn.close()
            except:
                pass

    def _safe_send(self, conn, msg_type, data):
        try:
            conn.sendall(pack_state(msg_type, data))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _handle_client(self, conn, name):
        while self.running:
            msg_type, data = recv_msg(conn)
            if msg_type is None:
                break
            with self.lock:
                if msg_type == MSG_STATE and data:
                    self.states[name] = {
                        'x': data[0], 'y': data[1], 'z': data[2],
                        'pitch': data[3], 'roll': data[4]
                    }
                elif msg_type == MSG_BALL and data:
                    self.ball = {
                        'x': data[0], 'y': data[1], 'z': data[2],
                        'vx': data[3], 'vy': data[4], 'vz': data[5]
                    }
        print(f'[Coord] {name} disconnected')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--duration', type=float, default=MATCH_DURATION)
    parser.add_argument('--n-teams', type=int, default=2)
    parser.add_argument('--log-dir', default='match_logs')
    parser.add_argument('--disturbance', action='store_true', help='Enable random push forces')
    parser.add_argument('--disturbance-interval', type=int, default=200, help='Steps between push')
    parser.add_argument('--disturbance-force', type=float, default=5.0, help='Max force (N)')
    parser.add_argument('--ball-random', action='store_true', help='Randomize ball start position')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()

    MATCH_DURATION = args.duration
    coord = MatchCoordinatorV3(
        args.port, args.n_teams, args.log_dir,
        disturbance=args.disturbance,
        dist_interval=args.disturbance_interval,
        dist_force=args.disturbance_force,
        ball_random=args.ball_random,
        seed=args.seed,
    )
    coord.run()
