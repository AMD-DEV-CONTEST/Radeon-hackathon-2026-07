import asyncio
import json
from urllib.parse import urlencode


def asgi_request(
    app,
    method,
    path,
    *,
    headers=None,
    params=None,
    json_body=None,
    body=None,
    content_type=None,
):
    if body is not None and json_body is not None:
        raise ValueError("body and json_body are mutually exclusive")
    body = body if body is not None else (b"" if json_body is None else json.dumps(json_body).encode("utf-8"))
    request_headers = {
        "host": "testserver",
        "content-type": content_type or "application/json",
        "content-length": str(len(body)),
        **(headers or {}),
    }
    messages = []

    async def run_request():
        delivered = False
        response_complete = asyncio.Event()

        async def receive():
            nonlocal delivered
            if delivered:
                await response_complete.wait()
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": urlencode(params or {}).encode("ascii"),
            "root_path": "",
            "headers": [
                (name.lower().encode("ascii"), value.encode("ascii"))
                for name, value in request_headers.items()
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        await app(scope, receive, send)

    asyncio.run(run_request())
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    if not response_body:
        payload = None
    else:
        try:
            payload = json.loads(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                payload = response_body.decode("utf-8")
            except UnicodeDecodeError:
                payload = response_body
    return start["status"], payload
