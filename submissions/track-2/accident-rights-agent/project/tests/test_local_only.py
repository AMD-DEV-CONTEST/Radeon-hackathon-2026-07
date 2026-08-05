from __future__ import annotations

import unittest

from app.policy.local_only import (
    LocalEndpointError,
    local_api_url,
    require_local_vllm_base_url,
)


class LocalOnlyTests(unittest.TestCase):
    def test_accepts_expected_ipv4_url(self) -> None:
        self.assertEqual(
            require_local_vllm_base_url("http://127.0.0.1:8000/v1"),
            "http://127.0.0.1:8000/v1",
        )

    def test_accepts_localhost_and_canonicalizes_path(self) -> None:
        self.assertEqual(
            require_local_vllm_base_url("http://localhost:8000"),
            "http://localhost:8000/v1",
        )

    def test_accepts_ipv6_loopback(self) -> None:
        self.assertEqual(
            require_local_vllm_base_url("http://[::1]:8000/v1"),
            "http://[::1]:8000/v1",
        )

    def test_rejects_public_host(self) -> None:
        with self.assertRaises(LocalEndpointError):
            require_local_vllm_base_url("https://api.example.com/v1")

    def test_rejects_lookalike_host(self) -> None:
        with self.assertRaises(LocalEndpointError):
            require_local_vllm_base_url("http://localhost.example.com:8000/v1")

    def test_rejects_public_bind_address(self) -> None:
        with self.assertRaises(LocalEndpointError):
            require_local_vllm_base_url("http://0.0.0.0:8000/v1")

    def test_rejects_wrong_port(self) -> None:
        with self.assertRaises(LocalEndpointError):
            require_local_vllm_base_url("http://127.0.0.1:8001/v1")

    def test_builds_api_path(self) -> None:
        self.assertEqual(
            local_api_url("/models", "http://127.0.0.1:8000/v1"),
            "http://127.0.0.1:8000/v1/models",
        )

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaises(LocalEndpointError):
            local_api_url("../models", "http://127.0.0.1:8000/v1")


if __name__ == "__main__":
    unittest.main()
