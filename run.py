"""Launch the MKO Web UI server.

Honors the MKO_HOST and MKO_PORT environment variables so the same script
works for local Windows development (defaults to 127.0.0.1:49239) and inside
the Docker container (compose sets MKO_HOST=0.0.0.0).
"""
import os
import uvicorn


def _coerce_port(raw: str, fallback: int = 49239) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


if __name__ == "__main__":
    uvicorn.run(
        "mko.webui.server:app",
        host=os.environ.get("MKO_HOST", "127.0.0.1"),
        port=_coerce_port(os.environ.get("MKO_PORT"), 49239),
        log_level="info",
        reload=False,
    )
