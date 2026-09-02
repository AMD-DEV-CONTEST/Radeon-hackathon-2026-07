import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "deploy" / "observability" / "radeon-exporter" / "exporter.py"
SPEC = importlib.util.spec_from_file_location("radeon_exporter", MODULE_PATH)
EXPORTER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(EXPORTER)


class RadeonExporterTest(unittest.TestCase):
    def test_parses_bounded_amd_smi_metrics(self):
        payload = {
            "gpu_0": {
                "GPU use (%)": "75%",
                "VRAM Total Memory (B)": 48 * 1024**3,
                "VRAM Used Memory (B)": 12 * 1024**3,
                "Temperature (Sensor edge) (C)": "61.0 C",
                "Average Graphics Package Power (W)": "144 W",
                "serial": "must-not-be-exported",
            }
        }
        values = {(name, gpu): value for name, gpu, value in EXPORTER.parse_metrics(payload)}
        self.assertEqual(values[("radeon_gpu_utilization_ratio", 0)], 0.75)
        self.assertEqual(values[("radeon_gpu_vram_total_bytes", 0)], 48 * 1024**3)
        self.assertEqual(values[("radeon_gpu_vram_used_bytes", 0)], 12 * 1024**3)
        self.assertNotIn("serial", " ".join(name for name, _ in values))

    def test_missing_collector_is_a_non_blocking_zero(self):
        original = EXPORTER.COMMANDS
        EXPORTER.COMMANDS = (("definitely-unavailable-command", "--json"),)
        try:
            rendered = EXPORTER.render()
        finally:
            EXPORTER.COMMANDS = original
        self.assertIn("radeon_gpu_exporter_up", rendered)
        self.assertIn('collector="unavailable"} 0', rendered)


if __name__ == "__main__":
    unittest.main()
