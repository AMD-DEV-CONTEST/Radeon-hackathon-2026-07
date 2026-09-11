from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from parcel_sorter.mobile_vla_controller import (
    PI05_BASE_MODEL_ENV,
    resolve_peft_base_checkpoint,
)


class MobileVLABaseOverrideTests(unittest.TestCase):
    def test_declared_adapter_path_is_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                resolve_peft_base_checkpoint("/models/pi05-droid"),
                "/models/pi05-droid",
            )

    def test_environment_override_supports_relocated_local_base(self) -> None:
        with patch.dict(
            os.environ,
            {PI05_BASE_MODEL_ENV: "/delivery/models/pi05-droid"},
            clear=True,
        ):
            self.assertEqual(
                resolve_peft_base_checkpoint("/remote/original/path"),
                "/delivery/models/pi05-droid",
            )

    def test_missing_declared_and_override_paths_fail_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, PI05_BASE_MODEL_ENV):
                resolve_peft_base_checkpoint(None)


if __name__ == "__main__":
    unittest.main()
