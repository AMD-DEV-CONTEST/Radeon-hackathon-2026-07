#!/usr/bin/env python3
"""Verify that a Linux TCP listener is bound only to loopback."""

from __future__ import annotations

import argparse
from pathlib import Path

TCP_LISTEN = "0A"
IPV4_LOOPBACK_HEX = "0100007F"
IPV6_LOOPBACK_HEX = "00000000000000000000000001000000"


def listeners(path: Path, port: int) -> list[str]:
    if not path.is_file():
        return []
    expected_port = f"{port:04X}"
    matches: list[str] = []
    for line in path.read_text(encoding="ascii").splitlines()[1:]:
        fields = line.split()
        if len(fields) < 4 or fields[3] != TCP_LISTEN:
            continue
        local_address, local_port = fields[1].split(":", 1)
        if local_port == expected_port:
            matches.append(local_address.upper())
    return matches


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", nargs="?", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")

    ipv4 = listeners(Path("/proc/net/tcp"), args.port)
    ipv6 = listeners(Path("/proc/net/tcp6"), args.port)
    found = [("ipv4", address) for address in ipv4] + [
        ("ipv6", address) for address in ipv6
    ]
    if not found:
        raise SystemExit(f"ERROR: no TCP listener found on port {args.port}.")

    unexpected = [
        (family, address)
        for family, address in found
        if not (
            (family == "ipv4" and address == IPV4_LOOPBACK_HEX)
            or (family == "ipv6" and address == IPV6_LOOPBACK_HEX)
        )
    ]
    if unexpected:
        raise SystemExit(
            f"ERROR: port {args.port} has a non-loopback listener: {unexpected}"
        )

    print(f"Listener check passed: port {args.port} is loopback-only ({found}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
