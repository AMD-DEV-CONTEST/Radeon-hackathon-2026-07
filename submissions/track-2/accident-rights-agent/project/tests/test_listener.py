from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.verify_loopback_listener import listeners


class ListenerParserTests(unittest.TestCase):
    def test_reads_only_requested_listen_socket(self) -> None:
        sample = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt
   0: 0100007F:1F40 00000000:0000 0A 00000000:00000000 00:00000000 00000000
   1: 00000000:22B8 00000000:0000 0A 00000000:00000000 00:00000000 00000000
   2: 0100007F:1F40 0100007F:9ABC 01 00000000:00000000 00:00000000 00000000
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tcp"
            path.write_text(sample, encoding="ascii")
            self.assertEqual(listeners(path, 8000), ["0100007F"])


if __name__ == "__main__":
    unittest.main()
