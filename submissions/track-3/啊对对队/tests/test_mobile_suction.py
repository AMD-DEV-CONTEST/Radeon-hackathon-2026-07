import unittest

from parcel_sorter.mobile_suction import discover_mobile_suction_cup_geoms


class _Geom:
    def __init__(self, index: int, name: str = "") -> None:
        self.idx = index
        self.name = name


class _Link:
    def __init__(self, name: str, geoms: list[_Geom]) -> None:
        self.name = name
        self.geoms = geoms


class MobileSuctionDiscoveryTests(unittest.TestCase):
    def test_discovers_three_named_cups_across_robot_links(self) -> None:
        robot = type(
            "Robot",
            (),
            {
                "links": [
                    _Link(
                        "tool",
                        [
                            _Geom(index, f"mobile_left_suction_cup_{index}_collision")
                            for index in range(3)
                        ],
                    )
                ]
            },
        )()
        self.assertEqual(discover_mobile_suction_cup_geoms(robot), frozenset({0, 1, 2}))

    def test_uses_audited_append_order_when_genesis_drops_names(self) -> None:
        robot = type(
            "Robot",
            (),
            {"links": [_Link("panda0_gripper", [_Geom(index) for index in range(7)])]},
        )()
        self.assertEqual(discover_mobile_suction_cup_geoms(robot), frozenset({4, 5, 6}))


if __name__ == "__main__":
    unittest.main()

