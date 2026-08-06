from __future__ import annotations

import http.client
import io
import re
import socket
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.demo import build_parser, run_read_only  # noqa: E402
from alphanoah_a1.exceptions import InvalidEventInput  # noqa: E402
from alphanoah_a1.qr_input import (  # noqa: E402
    IncidentReportInputError,
)
from alphanoah_a1.web import (  # noqa: E402
    LOCAL_HOST,
    MAX_REQUEST_BODY_BYTES,
    QRIncidentHTTPServer,
    create_server,
)


class QRIncidentReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_directory.name) / "qr-demo.sqlite3"
        self.server = create_server(self.database, port=0)
        self.adapter = self.server.adapter
        self.assertEqual(self.server.server_address[0], LOCAL_HOST)
        self.port = self.server.server_address[1]
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="alphanoah-qr-test-server",
            daemon=True,
        )
        self.server_thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        self.assertFalse(self.server_thread.is_alive())
        self.temp_directory.cleanup()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: str | bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], str]:
        connection = http.client.HTTPConnection(
            LOCAL_HOST, self.port, timeout=5
        )
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            response_body = response.read().decode("utf-8")
            return response.status, dict(response.getheaders()), response_body
        finally:
            connection.close()

    def get_form(self, query: dict[str, str] | None = None) -> tuple[str, str]:
        path = "/report"
        if query:
            path = f"{path}?{urlencode(query)}"
        status, _, body = self.request("GET", path)
        self.assertEqual(status, 200)
        match = re.search(
            r'name="submission_token" value="([^"]+)"',
            body,
        )
        self.assertIsNotNone(match)
        return match.group(1), body

    def post_form(
        self,
        token: str,
        fields: dict[str, str],
    ) -> tuple[int, dict[str, str], str]:
        body = urlencode({**fields, "submission_token": token})
        return self.request(
            "POST",
            "/report",
            body=body,
            headers={
                "Content-Type": (
                    "application/x-www-form-urlencoded; charset=utf-8"
                )
            },
        )

    def raw_request(self, request: bytes) -> tuple[int, str]:
        with socket.create_connection(
            (LOCAL_HOST, self.port), timeout=5
        ) as client:
            client.sendall(request)
            client.shutdown(socket.SHUT_WR)
            response = b""
            while True:
                part = client.recv(4096)
                if not part:
                    break
                response += part
        status_line = response.split(b"\r\n", 1)[0].decode("ascii")
        return int(status_line.split()[1]), response.decode(
            "utf-8", errors="replace"
        )

    @staticmethod
    def valid_fields() -> dict[str, str]:
        return {
            "asset_id": "PACK-003",
            "location": "Packaging-Line-A",
            "event_type": "equipment_issue_report",
            "reporter": "demo-operator",
            "description": "Synthetic abnormal equipment sound report.",
            "attachments": "synthetic://evidence/photo-001\n"
            "synthetic://evidence/note-001",
        }

    def test_01_valid_adapter_submission_creates_industrial_event(self):
        fields = self.valid_fields()
        fields["description"] = f"  {fields['description']}  "
        event = self.adapter.submit(fields)

        recovered = self.adapter.runtime.store.get_event(event.event_id)
        self.assertEqual(recovered.status.value, "NEW")
        self.assertEqual(recovered.event_type, "equipment_issue_report")
        self.assertEqual(
            recovered.description,
            "Synthetic abnormal equipment sound report.",
        )
        self.assertEqual(
            recovered.attachments,
            [
                "synthetic://evidence/photo-001",
                "synthetic://evidence/note-001",
            ],
        )
        self.assertEqual(
            recovered.metadata["data_classification"],
            "Synthetic demo data",
        )
        self.assertEqual(
            recovered.metadata["incident_notice"],
            "Not a real production incident",
        )

    def test_02_missing_description_is_rejected(self):
        token, _ = self.get_form()
        fields = self.valid_fields()
        fields["description"] = "   "

        status, _, body = self.post_form(token, fields)

        self.assertEqual(status, 400)
        self.assertIn("description is required", body)
        self.assertEqual(self.adapter.runtime.store.list_events(), [])

    def test_03_invalid_event_type_and_unknown_fields_are_rejected(self):
        token, _ = self.get_form()
        fields = self.valid_fields()
        fields["event_type"] = "Equipment-Fault"

        status, _, _ = self.post_form(token, fields)

        self.assertEqual(status, 400)
        with self.assertRaises(IncidentReportInputError):
            self.adapter.submit(
                {
                    **self.valid_fields(),
                    "metadata": '{"role": "admin"}',
                }
            )

        duplicate_token, _ = self.get_form()
        duplicate_fields = list(self.valid_fields().items())
        duplicate_fields.extend(
            (
                ("description", "Synthetic duplicate field."),
                ("submission_token", duplicate_token),
            )
        )
        duplicate_body = urlencode(duplicate_fields)
        status, _, _ = self.request(
            "POST",
            "/report",
            body=duplicate_body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(self.adapter.runtime.store.list_events(), [])

    def test_04_html_special_characters_are_escaped(self):
        token, headers, form = self._get_escaped_prefill_form()
        fields = self.valid_fields()
        fields["asset_id"] = "<script>alert(1)</script>"
        fields["location"] = 'Line "A" & Test'
        fields["description"] = '<img src=x onerror="alert(1)">'

        status, response_headers, body = self.post_form(token, fields)

        self.assertEqual(status, 201)
        self.assertNotIn("<img", body)
        self.assertIn("&lt;img", body)
        self.assertIn("default-src 'none'", response_headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        event = self.adapter.runtime.store.list_events()[0]
        self.assertEqual(event.description, fields["description"])

    def _get_escaped_prefill_form(
        self,
    ) -> tuple[str, dict[str, str], str]:
        query = {
            "asset_id": "<script>alert(1)</script>",
            "location": 'Line "A" & Test',
        }
        path = f"/report?{urlencode(query)}"
        status, headers, body = self.request("GET", path)
        self.assertEqual(status, 200)
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("&quot;A&quot; &amp; Test", body)
        match = re.search(
            r'name="submission_token" value="([^"]+)"',
            body,
        )
        self.assertIsNotNone(match)
        return match.group(1), headers, body

    def test_05_long_fields_and_oversized_requests_are_rejected(self):
        token, _ = self.get_form()
        fields = self.valid_fields()
        fields["asset_id"] = "A" * 129

        status, _, _ = self.post_form(token, fields)
        self.assertEqual(status, 400)

        oversized_body = b"x" * (MAX_REQUEST_BODY_BYTES + 1)
        status, _, _ = self.request(
            "POST",
            "/report",
            body=oversized_body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        self.assertEqual(status, 413)
        self.assertEqual(self.adapter.runtime.store.list_events(), [])

    def test_06_qr_prefill_values_reach_form_and_event(self):
        token, form = self.get_form(
            {
                "asset_id": "PACK-003",
                "location": "Packaging-Line-A",
            }
        )
        self.assertIn('value="PACK-003"', form)
        self.assertIn('value="Packaging-Line-A"', form)
        self.assertNotIn('name="metadata"', form)
        self.assertIn("does not automatically", form)

        status, _, body = self.post_form(token, self.valid_fields())

        self.assertEqual(status, 201)
        event = self.adapter.runtime.store.list_events()[0]
        self.assertEqual(event.asset_id, "PACK-003")
        self.assertEqual(event.location, "Packaging-Line-A")
        self.assertIn(event.event_id, body)
        self.assertIn(event.trace_id, body)
        self.assertIn("NEW", body)
        self.assertIn("No equipment diagnosis was performed", body)
        self.assertNotIn(str(self.database.resolve()), body)

    def test_07_created_event_is_visible_through_read_only_cli(self):
        token, _ = self.get_form()
        status, _, _ = self.post_form(token, self.valid_fields())
        self.assertEqual(status, 201)
        event = self.adapter.runtime.store.list_events()[0]

        commands = (
            ["--db", str(self.database), "list", "events"],
            ["--db", str(self.database), "show", "event", event.event_id],
            ["--db", str(self.database), "show", "trace", event.trace_id],
        )
        outputs: list[str] = []
        for command in commands:
            output = io.StringIO()
            with redirect_stdout(output):
                result = run_read_only(build_parser().parse_args(command))
            self.assertEqual(result, 0)
            outputs.append(output.getvalue())

        self.assertIn(event.event_id, outputs[0])
        self.assertIn('"event_type": "equipment_issue_report"', outputs[1])
        self.assertIn(f"Audit timeline ({event.trace_id})", outputs[2])
        self.assertIn("event_created", outputs[2])

    def test_08_http_layer_does_not_bypass_runtime_validation(self):
        token, _ = self.get_form()
        with patch.object(
            self.adapter.runtime,
            "create_event",
            side_effect=InvalidEventInput("Runtime contract rejection."),
        ) as create_event:
            status, _, body = self.post_form(token, self.valid_fields())

        self.assertEqual(status, 400)
        self.assertIn("Runtime rejected", body)
        create_event.assert_called_once()
        self.assertEqual(self.adapter.runtime.store.list_events(), [])

    def test_09_duplicate_submission_token_creates_only_one_event(self):
        token, _ = self.get_form()
        encoded = urlencode(
            {**self.valid_fields(), "submission_token": token}
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8"
        }

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda _: self.request(
                        "POST",
                        "/report",
                        body=encoded,
                        headers=headers,
                    ),
                    range(2),
                )
            )
        statuses = sorted(response[0] for response in responses)
        conflict_bodies = [
            response[2] for response in responses if response[0] == 409
        ]

        self.assertEqual(statuses, [201, 409])
        self.assertEqual(len(conflict_bodies), 1)
        self.assertIn("already submitted", conflict_bodies[0])
        self.assertEqual(len(self.adapter.runtime.store.list_events()), 1)

    def test_10_unexpected_methods_and_content_types_are_rejected(self):
        status, headers, _ = self.request("PUT", "/report")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "GET, POST")

        status, _, _ = self.request(
            "POST",
            "/report",
            body="{}",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 415)

        missing_length = (
            b"POST /report HTTP/1.0\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n\r\n"
        )
        status, _ = self.raw_request(missing_length)
        self.assertEqual(status, 411)

        invalid_length = (
            b"POST /report HTTP/1.0\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: +1\r\n\r\nx"
        )
        status, _ = self.raw_request(invalid_length)
        self.assertEqual(status, 400)

        excessive_length_digits = (
            b"POST /report HTTP/1.0\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: "
            + (b"9" * 5000)
            + b"\r\n\r\n"
        )
        status, _ = self.raw_request(excessive_length_digits)
        self.assertEqual(status, 400)

        token, _ = self.get_form()
        encoded = urlencode(
            {**self.valid_fields(), "submission_token": token}
        ).encode()
        duplicate_lengths = (
            b"POST /report HTTP/1.0\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            + (
                f"Content-Length: {len(encoded)}\r\n"
                f"Content-Length: {len(encoded) + 10}\r\n\r\n"
            ).encode()
            + encoded
        )
        status, _ = self.raw_request(duplicate_lengths)
        self.assertEqual(status, 400)

        token, _ = self.get_form()
        encoded = urlencode(
            {**self.valid_fields(), "submission_token": token}
        ).encode()
        transfer_encoding = (
            b"POST /report HTTP/1.0\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Transfer-Encoding: chunked\r\n"
            + f"Content-Length: {len(encoded)}\r\n\r\n".encode()
            + encoded
        )
        status, _ = self.raw_request(transfer_encoding)
        self.assertEqual(status, 400)

        token, _ = self.get_form()
        encoded = urlencode(
            {**self.valid_fields(), "submission_token": token}
        ).encode()
        incomplete_body = (
            b"POST /report HTTP/1.0\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            + f"Content-Length: {len(encoded) + 10}\r\n\r\n".encode()
            + encoded
        )
        status, _ = self.raw_request(incomplete_body)
        self.assertEqual(status, 400)

        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            QRIncidentHTTPServer(
                ("0.0.0.0", 0),
                self.adapter,
            )
        self.assertEqual(self.adapter.runtime.store.list_events(), [])


if __name__ == "__main__":
    unittest.main()
