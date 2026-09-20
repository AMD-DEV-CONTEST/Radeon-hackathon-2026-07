from __future__ import annotations

import json
import math
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "inference"))
import http_provider  # noqa: E402


def png(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), color).save(output, format="PNG")
    return output.getvalue()


def multipart() -> tuple[str, bytes]:
    boundary = "opendm-provider-test"
    body = bytearray()
    fields = {
        "text": "Unload cutlery.",
        "states": json.dumps([0.0] * 16),
        "request_id": "request-1",
    }
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode())
        body.extend(b"\r\n")
    for index, payload in enumerate(
        (png((255, 0, 0)), png((0, 255, 0)), png((0, 0, 255)))
    ):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                'Content-Disposition: form-data; name="image"; '
                f'filename="camera-{index}.png"\r\n'
                "Content-Type: image/png\r\n\r\n"
            ).encode()
        )
        body.extend(payload)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", bytes(body)


def identity() -> dict[str, str]:
    return {
        "provider": "opendm-dm05",
        "model_id": "fixture",
        "model_revision": "fixture-revision",
        "adapter_source_sha256": "a" * 64,
    }


def test_provider_v2_contract_slices_ten_actions() -> None:
    content_type, body = multipart()
    seen: dict = {}

    def infer(observation: dict, prompt: str) -> np.ndarray:
        seen.update(observation=observation, prompt=prompt)
        return np.zeros((16, 16), dtype=np.float32)

    app = http_provider.ProviderApp(infer, identity())
    response = app.process(content_type, body)
    assert response["request_id"] == "request-1"
    assert np.asarray(response["response"]).shape == (10, 16)
    assert seen["observation"]["state"].shape == (16,)
    assert [seen["observation"][key].shape for key in http_provider.CAMERA_KEYS] == [
        (8, 8, 3),
        (8, 8, 3),
        (8, 8, 3),
    ]
    assert seen["prompt"] == "Unload cutlery."
    assert all(
        math.isfinite(value) and value >= 0
        for value in response["timing_ms"].values()
    )


def test_provider_rejects_non_finite_actions() -> None:
    content_type, body = multipart()
    actions = np.zeros((10, 16), dtype=np.float32)
    actions[0, 0] = np.nan
    app = http_provider.ProviderApp(lambda _observation, _prompt: actions, identity())
    with pytest.raises(RuntimeError, match="non-finite"):
        app.process(content_type, body)


def test_provider_health_freezes_identity() -> None:
    app = http_provider.ProviderApp(
        lambda _observation, _prompt: np.zeros((10, 16)), identity()
    )
    health = app.health()
    assert health["status"] == "ok"
    assert health["protocol_version"] == 2
    assert health["policy_identity"] == identity()
