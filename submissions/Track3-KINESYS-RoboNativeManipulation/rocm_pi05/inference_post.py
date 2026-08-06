"""Server-side HTTP POST inference handler (paired with ``inference_server.py``).

The ``POST /infer`` endpoint receives a msgpack-encoded observation dict and returns a msgpack-encoded
action dict. Encode/decode with ``openpi_client.msgpack_numpy`` (``packb`` / ``unpackb``); plain JSON
cannot carry uint8 image arrays. This module holds only the request-handling logic so it is easy to
unit-test independently of the HTTP server.
"""

import json
import logging

from openpi_client import msgpack_numpy

log = logging.getLogger("openpi")


def handle_post(policy, body: bytes) -> tuple[int, bytes, str]:
    """Run inference on a msgpack request body.

    Returns:
        (status_code, response_bytes, content_type).
    """
    try:
        obs = msgpack_numpy.unpackb(body)
        action = policy.infer(obs)
        return 200, msgpack_numpy.packb(action), "application/msgpack"
    except Exception as e:  # noqa: BLE001 - surface any inference error to the client
        log.exception("inference failed")
        return 500, json.dumps({"error": str(e)}).encode(), "application/json"
