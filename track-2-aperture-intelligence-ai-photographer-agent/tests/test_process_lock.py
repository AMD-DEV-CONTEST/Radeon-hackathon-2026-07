from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ProcessLockTests(unittest.TestCase):
    def test_second_process_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = str(Path(directory) / "gpu.lock")
            env = {**os.environ, "AI_PHOTOGRAPHER_GPU_LOCK": lock_path}
            holder_code = (
                "import time; "
                "from src.vision.vlm_inference import _acquire_gpu_process_lock; "
                "lock=_acquire_gpu_process_lock(); print('locked', flush=True); time.sleep(10)"
            )
            holder = subprocess.Popen(
                [sys.executable, "-c", holder_code],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(holder.stdout.readline().strip(), "locked")
                contender = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        (
                            "from src.vision.vlm_inference import "
                            "_acquire_gpu_process_lock; _acquire_gpu_process_lock()"
                        ),
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertNotEqual(contender.returncode, 0)
                self.assertIn("already owns the GPU model", contender.stderr)
            finally:
                holder.terminate()
                holder.wait(timeout=3)
                if holder.stdout:
                    holder.stdout.close()
                if holder.stderr:
                    holder.stderr.close()


if __name__ == "__main__":
    unittest.main()
