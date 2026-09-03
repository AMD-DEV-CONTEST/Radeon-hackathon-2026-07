import logging
import time
from typing import Dict, Optional, Tuple

from typing_extensions import override
import websockets.sync.client

from openpi_client import base_policy as _base_policy
from openpi_client import msgpack_numpy


class WebsocketClientPolicy(_base_policy.BasePolicy):
    """Implements the Policy interface by communicating with a server over websocket.

    See WebsocketPolicyServer for a corresponding server implementation.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: Optional[int] = None,
        api_key: Optional[str] = None,
        *,
        ping_interval: float | None = 30,
        ping_timeout: float | None = 600,
        open_timeout: float | None = 30,
    ) -> None:
        if host.startswith("ws"):
            # Full URI (e.g. wss://tunnel.example.com) — port is already in the URL.
            self._uri = host
        elif port is not None:
            self._uri = f"ws://{host}:{port}"
        else:
            self._uri = f"ws://{host}"
        self._packer = msgpack_numpy.Packer()
        self._api_key = api_key
        self._connect_kwargs = {
            "compression": None,
            "max_size": None,
            "open_timeout": open_timeout,
            "ping_interval": ping_interval,
            "ping_timeout": ping_timeout,
        }
        self._ws, self._server_metadata = self._wait_for_server()

    def _connect(self) -> websockets.sync.client.ClientConnection:
        headers = {"Authorization": f"Api-Key {self._api_key}"} if self._api_key else None
        return websockets.sync.client.connect(
            self._uri,
            additional_headers=headers,
            **self._connect_kwargs,
        )

    def get_server_metadata(self) -> Dict:
        return self._server_metadata

    def _wait_for_server(self) -> Tuple[websockets.sync.client.ClientConnection, Dict]:
        logging.info(f"Waiting for server at {self._uri}...")
        while True:
            try:
                conn = self._connect()
                metadata = msgpack_numpy.unpackb(conn.recv())
                return conn, metadata
            except ConnectionRefusedError:
                logging.info("Still waiting for server...")
                time.sleep(5)

    def _reconnect(self) -> None:
        logging.warning(f"Reconnecting to server at {self._uri}...")
        try:
            self._ws.close()
        except Exception:
            pass
        self._ws, self._server_metadata = self._wait_for_server()

    @override
    def infer(self, obs: Dict) -> Dict:  # noqa: UP006
        data = self._packer.pack(obs)
        for attempt in range(2):
            try:
                self._ws.send(data)
                response = self._ws.recv()
                if isinstance(response, str):
                    # we're expecting bytes; if the server sends a string, it's an error.
                    raise RuntimeError(f"Error in inference server:\n{response}")
                return msgpack_numpy.unpackb(response)
            except websockets.exceptions.ConnectionClosed:
                if attempt == 0:
                    self._reconnect()
                    continue
                raise

    @override
    def reset(self) -> None:
        pass
