from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from cortex.bench.runner import BenchRunner


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m cortex.bench")
    parser.add_argument("--node", required=True, help="Org DID, e.g. did:percq:org:soc-alpha")
    parser.add_argument("--broker", required=True, help="Broker WebSocket URL, e.g. wss://broker.local:7432")
    parser.add_argument("--config", required=True, help="Path to bench.yaml")
    parser.add_argument("--tick-interval", type=float, default=None,
                        help="Override tick interval seconds (debug)")
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    kwargs = {}
    if args.tick_interval is not None:
        kwargs["tick_interval"] = args.tick_interval
    runner = BenchRunner(
        node_id=args.node,
        broker_url=args.broker,
        config_path=args.config,
        **kwargs,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_sigterm(*_):
        loop.create_task(runner.stop())

    try:
        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
        loop.add_signal_handler(signal.SIGINT, _handle_sigterm)
    except NotImplementedError:
        pass

    try:
        loop.run_until_complete(runner.run())
    except KeyboardInterrupt:
        loop.run_until_complete(runner.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
