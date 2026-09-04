"""CLI for fail-closed replay bundle verification."""
import argparse
from .replay import verify_bundle, ReplayVerificationError

def main(argv=None):
    parser = argparse.ArgumentParser(prog="nuclear-emergency-replay")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "replay"):
        command = sub.add_parser(name)
        command.add_argument("bundle")
    args = parser.parse_args(argv)
    try:
        # A deterministic rerun callback is deliberately not guessed by the CLI.
        if args.command == "replay":
            parser.error("replay requires an explicit deterministic rerun callback; use verify_bundle(..., rerun=callback)")
        result = verify_bundle(args.bundle)
    except (OSError, ValueError, ReplayVerificationError) as exc:
        parser.exit(1, f"verification failed: {exc}\n")
    print("valid" if result.valid else "invalid")
    return 0

if __name__ == "__main__":
    main()