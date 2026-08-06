"""Smoke test: display a Genesis Franka scene and advance simulation steps."""

import argparse

from simulation.task_factory import initialize_genesis, make_pick_place_env


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Genesis Franka smoke test.")
    parser.add_argument(
        "--viewer", action="store_true", help="Open a GUI viewer (requires an X11/desktop display)."
    )
    args = parser.parse_args()
    initialize_genesis(backend="gpu")
    env = make_pick_place_env(show_viewer=args.viewer)
    observation, _ = env.reset()
    action = observation["joint_position"]
    for _ in range(120):
        observation, reward, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            break
    print(f"Simulation stepped: reward={reward:.3f}, info={info}")


if __name__ == "__main__":
    main()
