#!/usr/bin/env python3
"""Analyze a multi-robot match JSON log and extract statistics."""
import json, os, math, sys

logfile = sys.argv[1] if len(sys.argv) > 1 else "match_logs/match_latest.json"
d = json.load(open(logfile))
log = d.get("log", [])

if not log:
    print("ERROR: Empty match log — no events recorded")
    sys.exit(1)

print(f"Duration: {d.get('duration')}")
print(f"N clients: {d.get('n_clients')}")
print(f"Steps: {d.get('steps')}")
print(f"Events: {len(log)}")

# Goal mouth half-width (field goal_width=2.6, half=1.3)
GOAL_HALF = 1.3

robot_ids = []
for e in log:
    if e.get("robots"):
        robot_ids = sorted(e["robots"].keys())
        break

# Note: client_N naming depends on connection order, not team assignment.
# Team A workers (ONNX, slower init) may connect after Team B (rule, faster init).
# The coordinator assigns client_0..5 by connection order.
# For accurate team attribution, the worker's --role arg (A_* = Team A, B_* = Team B)
# should be sent in the handshake. Until then, this analysis treats client_0-2 as
# Team A and client_3-5 as Team B, which MAY be incorrect.
print("WARNING: Team attribution based on connection order, not role identification.")
print("WARNING: If ONNX workers connect after rule workers, teams may be swapped.")
print(f"Robots: {robot_ids}")

ball_x = [e.get("ball", {}).get("x", 0) for e in log]
ball_y = [e.get("ball", {}).get("y", 0) for e in log]
print(f"Ball X range: [{min(ball_x):.2f}, {max(ball_x):.2f}]")
print(f"Ball Y range: [{min(ball_y):.2f}, {max(ball_y):.2f}]")

left_goals = right_goals = 0
for i in range(1, len(ball_x)):
    # Goal: ball crosses x=±7.0 AND |y| <= GOAL_HALF (1.3)
    if ball_x[i-1] < 7.0 and ball_x[i] >= 7.0 and abs(ball_y[i]) <= GOAL_HALF:
        right_goals += 1  # left team scored in right goal
    if ball_x[i-1] > -7.0 and ball_x[i] <= -7.0 and abs(ball_y[i]) <= GOAL_HALF:
        left_goals += 1  # right team scored in left goal
print(f"Left team goals (scored in right): {right_goals}")
print(f"Right team goals (scored in left): {left_goals}")

falls = {r: 0 for r in robot_ids}
recoveries = {r: 0 for r in robot_ids}
was_fallen = {r: False for r in robot_ids}
fall_times = {r: [] for r in robot_ids}
recovery_times = {r: [] for r in robot_ids}

for e in log:
    t = e.get("t", 0)
    for r_id in robot_ids:
        r = e.get("robots", {}).get(r_id, {})
        pitch = r.get("pitch", 0)
        z = r.get("z", 0.9)
        is_fallen = abs(pitch) > 1.5 or z < 0.5
        if is_fallen and not was_fallen[r_id]:
            falls[r_id] += 1
            was_fallen[r_id] = True
            fall_times[r_id].append(t)
        elif not is_fallen and was_fallen[r_id]:
            recoveries[r_id] += 1
            was_fallen[r_id] = False
            recovery_times[r_id].append(t)

total_falls = sum(falls.values())
total_recoveries = sum(recoveries.values())
print(f"\nTotal falls: {total_falls}")
print(f"Total recoveries: {total_recoveries}")
for r_id in robot_ids:
    avg_recovery = 0
    for ft, rt in zip(fall_times[r_id], recovery_times[r_id]):
        avg_recovery += rt - ft
    if recovery_times[r_id]:
        avg_recovery /= len(recovery_times[r_id])
    print(f"  {r_id}: falls={falls[r_id]}, recoveries={recoveries[r_id]}, avg_recovery={avg_recovery:.2f}s")

left_poss = 0
right_poss = 0
for e in log:
    ball = e.get("ball", {})
    bx, by = ball.get("x", 0), ball.get("y", 0)
    left_min = right_min = 999
    for r_id in robot_ids:
        r = e.get("robots", {}).get(r_id, {})
        rx, ry = r.get("x", 0), r.get("y", 0)
        dist = math.sqrt((rx-bx)**2 + (ry-by)**2)
        idx = int(r_id.split("_")[1])
        if idx < 3:
            left_min = min(left_min, dist)
        else:
            right_min = min(right_min, dist)
    if left_min < right_min:
        left_poss += 1
    else:
        right_poss += 1
print(f"\nBall possession: Left={left_poss} ({left_poss/len(log)*100:.1f}%), Right={right_poss} ({right_poss/len(log)*100:.1f}%)")

last = log[-1]
print("\nFinal positions:")
for r_id in robot_ids:
    r = last.get("robots", {}).get(r_id, {})
    print(f"  {r_id}: x={r.get('x',0):.3f} y={r.get('y',0):.3f} z={r.get('z',0):.3f} pitch={r.get('pitch',0):.3f}")
ball = last.get("ball", {})
print(f"  Ball: x={ball.get('x',0):.3f} y={ball.get('y',0):.3f} z={ball.get('z',0):.3f}")

print(f"\nAbnormal exit: {'NO' if len(log) == d.get('steps', 0) else 'YES'}")
