from unittest.mock import patch

import media_gateway


def test_catalog_has_only_unique_ids():
    ids = [item["id"] for item in media_gateway.MODEL_CATALOG]
    assert len(ids) == len(set(ids))
    assert {"image", "video"} == {item["kind"] for item in media_gateway.MODEL_CATALOG}


def test_image_payload_is_allowlisted_and_compact():
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update(method=method, path=path, payload=payload)
        return {"code": 200, "data": [{"status": "submitted", "task_id": "task_12345678"}]}

    with patch.object(media_gateway, "_provider_request", fake_request):
        result = media_gateway.submit(
            {
                "kind": "image",
                "model": "gpt-image-2",
                "prompt": "ink-water Go world",
                "size": "16:9",
                "resolution": "2k",
                "n": 1,
                "imageUrls": [],
            }
        )

    assert captured["path"] == "/images/generations"
    assert captured["payload"]["model"] == "gpt-image-2"
    assert "image_urls" not in captured["payload"]
    assert result["taskId"] == "task_12345678"


def test_unknown_model_is_rejected_before_network():
    try:
        media_gateway.submit(
            {"kind": "image", "model": "unrestricted-proxy", "prompt": "test"}
        )
    except media_gateway.MediaGatewayError as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("unknown model should be rejected")


def test_task_id_validation():
    try:
        media_gateway.task("../secret")
    except media_gateway.MediaGatewayError as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("unsafe task id should be rejected")


def test_reference_scheme_validation():
    try:
        media_gateway.submit(
            {
                "kind": "image",
                "model": "gpt-image-2",
                "prompt": "test reference",
                "imageUrls": ["file:///C:/secret.png"],
            }
        )
    except media_gateway.MediaGatewayError as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("local file references should be rejected")
