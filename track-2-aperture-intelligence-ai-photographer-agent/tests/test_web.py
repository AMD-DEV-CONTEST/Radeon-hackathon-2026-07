from __future__ import annotations

import base64
import unittest

from src.web import _decode_image


class WebInputTests(unittest.TestCase):
    def test_decode_valid_jpeg_payload(self) -> None:
        raw = b"\xff\xd8\xff\xe0test"
        encoded = base64.b64encode(raw).decode()
        payload, suffix = _decode_image(f"data:image/jpeg;base64,{encoded}")
        self.assertEqual(payload, raw)
        self.assertEqual(suffix, ".jpg")

    def test_reject_non_image_and_malformed_base64(self) -> None:
        with self.assertRaisesRegex(ValueError, "Only JPEG"):
            _decode_image("data:text/plain;base64,dGVzdA==")
        with self.assertRaises(ValueError):
            _decode_image("data:image/png;base64,not-valid!")


if __name__ == "__main__":
    unittest.main()
