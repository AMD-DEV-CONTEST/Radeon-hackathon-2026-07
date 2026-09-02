import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from scripts.build_dashboard_radeon_evidence import build_report


class DashboardRadeonEvidenceTests(unittest.TestCase):
    def test_builds_synchronized_local_and_hybrid_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local = root / "local.json"
            hybrid = root / "hybrid.json"
            local.write_text(json.dumps(journey("local_only", ["local_rocm"], ["local-rocm"])))
            hybrid.write_text(
                json.dumps(
                    journey(
                        "hybrid_radeon_api",
                        ["provided_radeon_api", "local_rocm"],
                        ["radeon-vllm", "local-rocm"],
                    )
                )
            )
            captures = {}
            for name in ("local_plan", "local_mission", "hybrid_plan", "hybrid_mission"):
                captures[name] = root / f"{name}.png"
                captures[name].write_bytes(png(1280, 720))

            report = build_report(local, hybrid, captures, "a" * 64, "b" * 64)

            self.assertEqual(report["decision"]["status"], "passed")
            self.assertFalse(report["decision"]["exact_release_artifact"])
            self.assertEqual(report["journeys"]["local"]["routes"], ["local_rocm"])
            self.assertEqual(
                report["journeys"]["hybrid"]["routes"],
                ["local_rocm", "provided_radeon_api"],
            )
            self.assertEqual(report["captures"]["hybrid_plan"]["width"], 1280)

    def test_rejects_hybrid_without_local_fallback_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local = root / "local.json"
            hybrid = root / "hybrid.json"
            local.write_text(json.dumps(journey("local_only", ["local_rocm"], ["local-rocm"])))
            hybrid.write_text(
                json.dumps(
                    journey("hybrid_radeon_api", ["provided_radeon_api"], ["radeon-vllm"])
                )
            )
            captures = {}
            for name in ("local_plan", "local_mission", "hybrid_plan", "hybrid_mission"):
                captures[name] = root / f"{name}.png"
                captures[name].write_bytes(png(1280, 720))

            with self.assertRaisesRegex(ValueError, "fallback"):
                build_report(local, hybrid, captures, "a" * 64, "b" * 64)


def journey(mode, routes, providers):
    return {
        "schema_version": "signalforge/dashboard-radeon-journey/v1",
        "mode": mode,
        "status": "completed",
        "run_id": f"run-{mode}",
        "trace_id": f"trace-{mode}",
        "source_trace_sha256": "c" * 64,
        "privacy": {
            "credentials_retained": False,
            "prompt_bodies_retained": False,
            "response_bodies_retained": False,
            "source_bodies_retained": False,
        },
        "execution_plan": {
            "status": "passed",
            "progress_ratio": 1,
            "terminal_steps": 12,
            "total_steps": 12,
            "projection_sha256": "d" * 64,
            "phases": [
                {"phase_id": phase, "status": "passed"}
                for phase in (
                    "interpretation",
                    "planning",
                    "context",
                    "tools",
                    "review",
                    "synthesis",
                    "memory",
                    "release",
                )
            ],
        },
        "intelligence": {
            "release_status": "released",
            "model_calls": 12,
            "routes": routes,
            "providers": providers,
        },
    }


def png(width, height):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + b"\xff\xff\xff" * width
    data = zlib.compress(row * height)
    return header + chunk(b"IHDR", ihdr) + chunk(b"IDAT", data) + chunk(b"IEND", b"")


if __name__ == "__main__":
    unittest.main()
