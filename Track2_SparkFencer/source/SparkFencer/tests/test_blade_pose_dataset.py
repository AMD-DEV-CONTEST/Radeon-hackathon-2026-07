import tempfile
import unittest
from pathlib import Path

from fencing_analysis.blade_pose_dataset import (
    BladeAnnotation, ensure_dataset, label_path_for, load_annotations,
    save_annotations, validate_dataset,
)


class BladePoseDatasetTest(unittest.TestCase):
    def test_yolo_pose_round_trip_and_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = ensure_dataset(Path(temporary) / "blade")
            image_path = root / "images" / "train" / "sample.jpg"
            image_path.touch()
            labels = [BladeAnnotation(guard=(10.0, 20.0), tip=(90.0, 30.0))]
            path = label_path_for(image_path, root, "train")
            self.assertEqual(save_annotations(path, labels, 100, 80), 1)
            restored = load_annotations(path, 100, 80)
            self.assertEqual(len(restored), 1)
            self.assertAlmostEqual(restored[0].guard[0], 10.0, places=3)
            self.assertAlmostEqual(restored[0].tip[1], 30.0, places=3)
            validation = validate_dataset(root, require_labels=True)
            self.assertTrue(validation["valid"], validation["problems"])

    def test_incomplete_instance_is_not_serialized(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = ensure_dataset(Path(temporary) / "blade")
            path = root / "labels" / "train" / "empty.txt"
            count = save_annotations(path, [BladeAnnotation(guard=(10, 10))], 100, 100)
            self.assertEqual(count, 0)
            self.assertEqual(path.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
