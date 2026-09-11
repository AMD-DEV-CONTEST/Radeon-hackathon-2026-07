import unittest

from parcel_sorter.capabilities import (
    SUPPORTED_HANDLING_CLASSES,
    UnsupportedHandlingClassError,
    require_supported_handling,
)


class CapabilityTests(unittest.TestCase):
    def test_parallel_jaw_is_the_current_runtime_capability(self) -> None:
        self.assertEqual(SUPPORTED_HANDLING_CLASSES, {"parallel_jaw"})
        require_supported_handling("parallel_jaw")

    def test_unsupported_end_effector_fails_with_actionable_message(self) -> None:
        with self.assertRaisesRegex(
            UnsupportedHandlingClassError,
            "suction_required.*parallel_jaw",
        ):
            require_supported_handling("suction_required")

    def test_capability_registry_can_be_extended_explicitly(self) -> None:
        require_supported_handling("suction", supported={"parallel_jaw", "suction"})


if __name__ == "__main__":
    unittest.main()
