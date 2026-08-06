"""Match Coordinator v2: stable single-robot/multi-robot sync with logging.

Fixes:
  - SIGPIPE ignored globally
  - All sends wrapped in try/except
  - Configurable match duration and broadcast rate (``--sync-hz``)
  - Structured JSON match log with timestamps
  - Graceful shutdown
"""
import argparse, socket, json, threading, time, signal, os, sys, math
from datetime import datetime

from match_protocol import (
    MSG_STATE, MSG_BALL, MSG_CMD, MSG_END, MSG_WORLD, MSG_HELLO,
    pack_handshake, pack_state, recv_msg, validate_identity,
)

DEFAULT_PORT = 9876
MATCH_DURATION = 20.0
SYNC_HZ = 50
COLLISION_DIST = 0.3
END_GRACE_SECONDS = 0.5
class MatchCoordinator:
    def __init__(self, port=DEFAULT_PORT, n_teams=2, log_dir='match_logs',
                 sync_hz=SYNC_HZ):
        self.port = port
        self.n_teams = n_teams
        if not math.isfinite(sync_hz) or sync_hz <= 0:
            raise ValueError('sync_hz must be positive')
        self.sync_hz = float(sync_hz)
        self.running = False
        self.ending = False
        self.clients = {}  # name -> (conn, addr)
        self.client_threads = []
        self.handler_errors = []
        self.identities = {}
        self.identity_received = {}
        self.identity_errors = []
        self.states = {}   # name -> {x, y, z, pitch, roll}
        self.ball = {'x': 0, 'y': 0, 'z': 0.11, 'vx': 0, 'vy': 0, 'vz': 0}
        self.lock = threading.Lock()
        self.log_dir = log_dir
        self.match_log = []
        self.start_time = None

        os.makedirs(log_dir, exist_ok=True)

    def run(self):
        # Ignore SIGPIPE so broken sockets don't kill the process
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        self.running = True
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('localhost', self.port))
        server.listen(self.n_teams * 3 + 2)
        print(f'[Coord] Listening on port {self.port}, expecting up to {self.n_teams*3} clients')

        # Accept clients with 600s total deadline (workers need time to compile Genesis kernels)
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
            self.identities[name] = {
                'team': 'unknown',
                'role': 'unknown',
                'controller': 'legacy',
                'model_sha': 'unknown',
                'ball_authority': False,
            }
            self.identity_received[name] = False
            self.states[name] = {'x': 0, 'y': 0, 'z': 0.7, 'pitch': 0, 'roll': 0}
            print(f'[Coord] {name} connected from {addr} ({connected+1}/{expected})')
            client_thread = threading.Thread(
                target=self._handle_client, args=(conn, name), daemon=True)
            client_thread.start()
            self.client_threads.append(client_thread)
            connected += 1

        if connected < expected:
            print(f'[Coord] Warning: only {connected}/{expected} clients connected')
        print(f'[Coord] All clients connected, starting match')

        server.settimeout(None)
        self.start_time = time.time()

        # Main sync loop
        while self.running and time.time() - self.start_time < MATCH_DURATION:
            elapsed = time.time() - self.start_time

            with self.lock:
                states_snapshot = {k: dict(v) for k, v in self.states.items()}
                ball_snapshot = dict(self.ball)
                identities_snapshot = {k: dict(v) for k, v in self.identities.items()}

            # Collision detection (pairwise)
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

            # Broadcast to all clients
            client_names = list(self.clients.keys())
            n_robots = len(client_names)

            # Build world state array: [n_robots * 5 (x,y,z,pitch,roll)] + [ball_x,ball_y,ball_z,ball_vx,ball_vy,ball_vz]
            # Total floats = n_robots*5 + 6
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
                # Send global world state (all robots + ball)
                self._safe_send(conn, MSG_WORLD, world_data)

                # Send collision push-back
                # Always send collision push-back (even if zero, to keep protocol in sync)
                push = [0, 0, 0]
                for c in collisions:
                    if name == c[0]:
                        push[0] = c[3] / c[2] * 0.1
                        push[1] = c[4] / c[2] * 0.1
                    elif name == c[1]:
                        push[0] = -c[3] / c[2] * 0.1
                        push[1] = -c[4] / c[2] * 0.1
                self._safe_send(conn, MSG_CMD, push)

            # Log match state
            log_entry = {
                't': round(elapsed, 3),
                'ball': {k: round(v, 4) for k, v in ball_snapshot.items()},
                'robots': {
                    k: {
                        kk: (bool(vv) if kk in ('fallen', 'scored') else round(vv, 4))
                        for kk, vv in v.items()
                    }
                    for k, v in states_snapshot.items()
                },
                # Event state is attached to every frame, including false
                # values, so downstream metrics can distinguish no event from
                # missing telemetry.  This mapping is identity-keyed, never
                # inferred from accept order.
                'events': {
                    k: {
                        'fallen': bool(v.get('fallen', False)),
                        # Only the declared ball authority can claim a goal;
                        # other workers may report the same shared ball event.
                        'scored': bool(v.get('scored', False)) and bool(
                            identities_snapshot.get(k, {}).get('ball_authority', False)),
                    }
                    for k, v in states_snapshot.items()
                },
                'collisions': len(collisions),
            }
            self.match_log.append(log_entry)

            time.sleep(1.0 / self.sync_hz)

        # Signal end to all clients and keep the write side open long enough
        # for every worker to consume the frame before the socket is closed.
        self.ending = True
        end_send_failures = self._broadcast_end()

        # Save match log
        elapsed = time.time() - self.start_time if self.start_time else 0
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = os.path.join(self.log_dir, f'match_{timestamp}.json')
        identity_errors = self._identity_contract_errors(expected)
        with self.lock:
            identities_snapshot = {k: dict(v) for k, v in self.identities.items()}
        with open(log_path, 'w') as f:
            json.dump({
                'duration': round(elapsed, 2),
                'n_clients': len(self.clients),
                'sync_hz': self.sync_hz,
                'identities': identities_snapshot,
                'identity_source': (
                    'worker-declared handshake; validated'
                    if not identity_errors else
                    'worker-declared handshake; validation failed'
                ),
                'identity_errors': identity_errors,
                'steps': len(self.match_log),
                'log': self.match_log,
            }, f, indent=2)

        print(f'[Coord] Match ended after {elapsed:.1f}s, {len(self.match_log)} steps logged')
        print(f'[Coord] Log saved to {log_path}')
        self.running = False

        # Stop handler reads explicitly, then give each thread a bounded
        # chance to observe shutdown before closing the descriptor.
        for conn in self.clients.values():
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for client_thread in self.client_threads:
            client_thread.join(timeout=1.0)

        # Close all connections
        for conn in self.clients.values():
            try:
                conn.close()
            except:
                pass

        return 1 if end_send_failures or connected < expected or self.handler_errors or identity_errors else 0

    def _safe_send(self, conn, msg_type, data):
        try:
            conn.sendall(pack_state(msg_type, data))
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _broadcast_end(self):
        """Send MSG_END, half-close writes, and return failed send count."""
        failures = 0
        clients = list(self.clients.values())
        for conn in clients:
            if not self._safe_send(conn, MSG_END, []):
                failures += 1

        # SHUT_WR makes the send boundary explicit while preserving the read
        # side.  Workers therefore see MSG_END before EOF even if their final
        # state send races with coordinator shutdown.
        for conn in clients:
            try:
                conn.shutdown(socket.SHUT_WR)
            except (OSError, socket.error):
                pass
        if clients and END_GRACE_SECONDS > 0:
            time.sleep(END_GRACE_SECONDS)
        return failures

    def _handle_client(self, conn, name):
        first_message = True
        try:
            while self.running:
                msg_type, data = recv_msg(conn)
                if msg_type is None:
                    if not self.ending:
                        with self.lock:
                            self.handler_errors.append(f'{name}: connection closed')
                    break
                if msg_type == MSG_HELLO:
                    if not first_message:
                        with self.lock:
                            self.identity_errors.append(f'{name}: duplicate identity handshake')
                        break
                    first_message = False
                    self._bind_identity(name, data)
                    continue
                if first_message:
                    # Keep decoding legacy 5-field state frames, but mark the
                    # connection incomplete so a normal match cannot claim a
                    # fully declared identity set.
                    first_message = False
                    with self.lock:
                        self.identity_errors.append(f'{name}: first frame was not HELLO')
                with self.lock:
                    if msg_type == MSG_STATE and data:
                        self.states[name] = {
                            'x': data[0], 'y': data[1], 'z': data[2],
                            'pitch': data[3], 'roll': data[4]
                        }
                        if len(data) >= 6:
                            self.states[name]['fallen'] = bool(data[5])
                        if len(data) >= 7:
                            self.states[name]['scored'] = bool(data[6])
                    elif msg_type == MSG_BALL and data:
                        self.ball = {
                            'x': data[0], 'y': data[1], 'z': data[2],
                            'vx': data[3], 'vy': data[4], 'vz': data[5]
                        }
        except (ConnectionResetError, BrokenPipeError, OSError) as exc:
            if not self.ending:
                with self.lock:
                    self.handler_errors.append(f'{name}: {exc!r}')
        except Exception as exc:
            with self.lock:
                self.handler_errors.append(f'{name}: unexpected {exc!r}')
        finally:
            print(f'[Coord] {name} disconnected')

    def _bind_identity(self, name, identity):
        """Validate and bind the first worker-declared identity exactly once."""
        normalized = validate_identity(identity, strict=True)
        with self.lock:
            if self.identity_received.get(name, False):
                self.identity_errors.append(f'{name}: identity already bound')
                return
            self.identities[name] = normalized
            self.identity_received[name] = True

    def _identity_contract_errors(self, expected):
        """Return missing/duplicate identity errors for the match summary."""
        with self.lock:
            errors = list(self.identity_errors)
            names = list(self.clients)
            identities = {name: dict(self.identities.get(name, {})) for name in names}
            received = dict(self.identity_received)
        if len(names) != expected:
            errors.append(f'expected {expected} clients, got {len(names)}')
        for name in names:
            if not received.get(name, False):
                errors.append(f'{name}: missing worker-declared identity')
        combinations = []
        authority_names = []
        for name, identity in identities.items():
            try:
                normalized = validate_identity(identity, strict=True)
            except ValueError as exc:
                errors.append(f'{name}: invalid identity: {exc}')
                continue
            combinations.append((normalized['team'], normalized['role']))
            if normalized['ball_authority']:
                authority_names.append(name)
        if len(combinations) != len(set(combinations)):
            errors.append('worker-declared team/role identities are not unique')
        if expected == 6 and set(combinations) != {
            ('A', 'attacker'), ('A', 'defender'), ('A', 'keeper'),
            ('B', 'attacker'), ('B', 'defender'), ('B', 'keeper'),
        }:
            errors.append('multi-robot worker-declared identity set is incomplete')
        if expected == 6:
            if len(authority_names) != 1:
                errors.append('multi-robot requires exactly one ball_authority worker')
            elif not (
                identities[authority_names[0]].get('team') == 'A'
                and identities[authority_names[0]].get('role') == 'attacker'
                and identities[authority_names[0]].get('controller') == 'ONNX'
            ):
                errors.append('ball_authority must be the A ONNX attacker')
            for team in ('A', 'B'):
                team_members = [item for item in identities.values() if item.get('team') == team]
                if len(team_members) != 3:
                    errors.append(f'team {team} must declare exactly three workers')
            for item in identities.values():
                expected_controller = 'ONNX' if item.get('team') == 'A' else 'Rule'
                if item.get('controller') != expected_controller:
                    errors.append(f"{item.get('team')} controller must be {expected_controller}")
        return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--duration', type=float, default=MATCH_DURATION)
    parser.add_argument('--n-teams', type=int, default=2, help='2 for single-robot, 6 for multi-robot')
    parser.add_argument('--sync-hz', type=float, default=SYNC_HZ,
                        help='Coordinator broadcast rate (default: 50; multi-robot launcher uses 2)')
    parser.add_argument('--log-dir', default='match_logs')
    args = parser.parse_args()
    MATCH_DURATION = args.duration
    coord = MatchCoordinator(args.port, args.n_teams, args.log_dir, args.sync_hz)
    sys.exit(coord.run() or 0)
