from __future__ import annotations

import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from alphanoah_a1.provider_orchestration import ResolvedProviderRuntime
from alphanoah_a1.providers.fake import ReadinessFakeAnalysisProvider
from alphanoah_a1.web_api import create_server


class LocalReleaseStaticTests(unittest.TestCase):
    def test_static_frontend_and_api_share_one_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("edge-ui", encoding="utf-8")
            server = create_server(
                root / "runtime.sqlite3",
                port=0,
                provider_runtime=ResolvedProviderRuntime.injected(
                    ReadinessFakeAnalysisProvider()
                ),
                static_directory=root,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({})
                )
                with opener.open(
                    f"http://127.0.0.1:{port}/"
                ) as response:
                    self.assertEqual(response.read(), b"edge-ui")
                with opener.open(
                    f"http://127.0.0.1:{port}/api/health"
                ) as response:
                    self.assertIn(b"fake", response.read())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
