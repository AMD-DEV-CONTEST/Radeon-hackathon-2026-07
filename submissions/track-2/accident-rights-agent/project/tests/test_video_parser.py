from __future__ import annotations

import unittest

from app.evidence.video_parser import (
    FrameCandidate,
    _limit_with_temporal_coverage,
    hamming_distance,
)


class VideoParserTests(unittest.TestCase):
    def test_hamming_distance(self) -> None:
        self.assertEqual(hamming_distance(0b1010, 0b1111), 2)

    def test_frame_limit_preserves_first_and_last(self) -> None:
        candidates = [
            FrameCandidate(
                frame_index=index,
                timestamp_seconds=float(index),
                image=None,
                blur_score=100,
                brightness=100,
                scene_delta=10,
                perceptual_hash=index,
            )
            for index in range(10)
        ]
        selected = _limit_with_temporal_coverage(candidates, 4)
        self.assertEqual(len(selected), 4)
        self.assertEqual(selected[0].frame_index, 0)
        self.assertEqual(selected[-1].frame_index, 9)


if __name__ == "__main__":
    unittest.main()
