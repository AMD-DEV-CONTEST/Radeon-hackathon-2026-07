import unittest

from parcel_sorter.mobile_cradle import update_cradle_contact_memory_offset


class MobileCradleContactMemoryTests(unittest.TestCase):
    def test_lost_contact_accumulates_only_to_bounded_authority(self) -> None:
        offset = 0.0
        for _ in range(200):
            offset = update_cradle_contact_memory_offset(
                offset, contact_geoms=0, contact_force_n=0.0
            )
        self.assertEqual(offset, 0.005)

    def test_low_force_contact_holds_and_high_force_releases_offset(self) -> None:
        contact_hold = update_cradle_contact_memory_offset(
            0.001, contact_geoms=1, contact_force_n=5.0
        )
        force_release = update_cradle_contact_memory_offset(
            0.001, contact_geoms=1, contact_force_n=25.0
        )
        self.assertEqual(contact_hold, 0.001)
        self.assertLess(force_release, contact_hold)

    def test_invalid_telemetry_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            update_cradle_contact_memory_offset(
                0.0, contact_geoms=-1, contact_force_n=0.0
            )


if __name__ == "__main__":
    unittest.main()
