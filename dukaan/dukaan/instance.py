"""Talk to the Radeon instance over the JupyterLab API.

The cloud hands out a JupyterLab URL and nothing else: no ssh, no scp. Its REST
API is enough for all three things a deploy needs, so that is the transport.

    contents API   files up and down
    kernels API    a python process to run things in
    websocket      that process's stdout, streamed back

Everything here is plain HTTP plus one websocket, so the same code path works
from a laptop, from CI, or from inside the instance itself.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import tarfile
import time
import uuid
from pathlib import Path

import requests
import websocket
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class InstanceError(RuntimeError):
    pass


class Instance:
    def __init__(self, base_url: str, timeout: int = 3600):
        if not base_url:
            raise InstanceError(
                "no instance URL. Set DUKAAN_INSTANCE to the JupyterLab base URL of the "
                "Radeon box, for example https://<host>/instances/<instance-id>"
            )
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        # The tunnel in front of the instance resets connections under load,
        # and a pack is worth minutes of GPU time, so a dropped socket must not
        # be the thing that loses it.
        self.http = requests.Session()
        retry = Retry(total=5, backoff_factor=1.5, status_forcelist=(500, 502, 503, 504),
                      allowed_methods=frozenset({"GET", "PUT", "POST", "DELETE"}))
        self.http.mount("https://", HTTPAdapter(max_retries=retry))
        self.http.mount("http://", HTTPAdapter(max_retries=retry))

    # --- files --------------------------------------------------------

    def put(self, local: str | Path, remote: str) -> None:
        payload = base64.b64encode(Path(local).read_bytes()).decode()
        r = self.http.put(
            f"{self.base}/api/contents/{remote}",
            json={"type": "file", "format": "base64", "content": payload},
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            raise InstanceError(
                f"upload of {remote} failed with {r.status_code}. The parent directory has "
                "to exist and be under the notebook root; run `dukaan deploy` first."
            )

    def put_bytes(self, data: bytes, remote: str) -> None:
        r = self.http.put(
            f"{self.base}/api/contents/{remote}",
            json={"type": "file", "format": "base64", "content": base64.b64encode(data).decode()},
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            raise InstanceError(f"upload of {remote} failed with {r.status_code}")

    def get(self, remote: str) -> bytes:
        r = self.http.get(f"{self.base}/api/contents/{remote}", params={"format": "base64"},
                         timeout=self.timeout)
        if r.status_code >= 400:
            raise InstanceError(f"download of {remote} failed with {r.status_code}")
        return base64.b64decode(r.json()["content"])

    def ls(self, remote: str) -> list[str]:
        r = self.http.get(f"{self.base}/api/contents/{remote}", timeout=self.timeout)
        if r.status_code >= 400:
            raise InstanceError(f"listing {remote} failed with {r.status_code}")
        return sorted(c["name"] for c in r.json().get("content", []))

    def get_dir(self, remote: str, abs_path: str) -> dict[str, bytes]:
        """Pull a whole directory back in one request.

        A clip is fifty files. Fetching them one at a time is fifty chances for
        the tunnel to reset the connection halfway through a run that already
        cost minutes of GPU time, and the base64 contents API is slow per call.
        Tarring on the instance turns that into a single transfer.
        """
        # The tar lands beside the directory, so the same path works for the
        # shell (absolute) and for the contents API (relative to the root).
        self.shell(f"tar czf {abs_path}.tgz -C {abs_path} .")
        try:
            blob = self.get(f"{remote}.tgz")
        finally:
            self.shell(f"rm -f {abs_path}.tgz")

        out: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    fh = tar.extractfile(member)
                    if fh:
                        out[Path(member.name).name] = fh.read()
        return out

    # --- execution ----------------------------------------------------

    def _new_kernel(self) -> str:
        r = self.http.post(f"{self.base}/api/kernels", json={"name": "python3"}, timeout=120)
        if r.status_code >= 400:
            raise InstanceError(f"could not start a kernel: {r.status_code}")
        return r.json()["id"]

    def run(self, code: str, timeout: int | None = None, echo: bool = False) -> str:
        """Run python on the instance and return everything it printed.

        Kernels get culled when idle and the platform restarts the container
        under memory pressure, so a kernel is started per call rather than
        cached: a dead kernel is a far more confusing failure than the cost of
        starting a fresh one.
        """
        timeout = timeout or self.timeout
        kid = self._new_kernel()
        ws_url = self.base.replace("https://", "wss://").replace("http://", "ws://")

        # Retry only the connect. Once the execute_request is on the wire a
        # dropped socket is ambiguous, and re-sending it could start a second
        # GPU job; a failure to connect ran nothing, so it is safe to repeat.
        ws = None
        for attempt in range(5):
            try:
                ws = websocket.create_connection(f"{ws_url}/api/kernels/{kid}/channels", timeout=60)
                break
            except (websocket.WebSocketException, OSError) as exc:
                if attempt == 4:
                    raise InstanceError(f"could not open a kernel channel: {exc}") from exc
                time.sleep(1.5 * (attempt + 1))
        msg_id = uuid.uuid4().hex
        ws.send(json.dumps({
            "header": {"msg_id": msg_id, "username": "dukaan", "session": uuid.uuid4().hex,
                       "msg_type": "execute_request", "version": "5.3"},
            "parent_header": {}, "metadata": {},
            "content": {"code": code, "silent": False, "store_history": False,
                        "user_expressions": {}, "allow_stdin": False, "stop_on_error": True},
            "channel": "shell",
        }))

        out: list[str] = []
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                ws.settimeout(max(1.0, deadline - time.time()))
                try:
                    frame = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                # Jupyter sends binary frames for messages carrying buffers, and
                # an empty frame on a half-closed socket. Neither is ours, and
                # neither should end a run that is still going.
                if not frame:
                    continue
                try:
                    m = json.loads(frame)
                except (ValueError, TypeError):
                    continue
                if m.get("parent_header", {}).get("msg_id") != msg_id:
                    continue
                kind = m["header"]["msg_type"]
                if kind == "stream":
                    out.append(m["content"]["text"])
                    if echo:
                        sys.stdout.write(m["content"]["text"])
                        sys.stdout.flush()
                elif kind == "error":
                    raise InstanceError(
                        f"{m['content']['ename']}: {m['content']['evalue']}\n"
                        + "\n".join(m["content"].get("traceback", [])[-6:])
                    )
                elif kind == "status" and m["content"]["execution_state"] == "idle":
                    break
            else:
                raise InstanceError(f"instance did not finish within {timeout}s")
        finally:
            ws.close()
            try:
                self.http.delete(f"{self.base}/api/kernels/{kid}", timeout=60)
            except requests.RequestException:
                pass
        return "".join(out)

    def shell(self, cmd: str, timeout: int | None = None, echo: bool = False) -> str:
        code = (
            "import subprocess, sys\n"
            f"p = subprocess.Popen({cmd!r}, shell=True, stdout=subprocess.PIPE,\n"
            "                     stderr=subprocess.STDOUT, text=True, bufsize=1)\n"
            "for line in p.stdout:\n"
            "    sys.stdout.write(line); sys.stdout.flush()\n"
            "sys.stdout.write('EXIT %d\\n' % p.wait())\n"
        )
        return self.run(code, timeout=timeout, echo=echo)

    def detach(self, cmd: str, log: str) -> None:
        """Start a long job that outlives the kernel that launched it.

        A ComfyUI model load can outlast the websocket, and a culled kernel
        would take a child process down with it. setsid detaches the job so
        progress can be read back from its log instead.
        """
        self.shell(f"setsid nohup {cmd} > {log} 2>&1 < /dev/null & echo started")

    def wait_for(self, log: str, done: str, fail: str = "Traceback",
                 timeout: int = 1800, poll: float = 5.0, tolerate: int = 12) -> str:
        """Poll a detached job's log until it says it finished, or blew up.

        A failed poll is not a failed job. The job is detached and the tunnel
        drops connections often enough that a reset while reading the log would
        otherwise throw away a run that is still going and already cost GPU
        time. Transient errors are counted rather than raised, and only a run
        of them means the instance is really gone.
        """
        deadline = time.time() + timeout
        misses = 0
        while time.time() < deadline:
            try:
                text = self.shell(f"cat {log} 2>/dev/null || true")
                misses = 0
            except (InstanceError, requests.RequestException, websocket.WebSocketException,
                    OSError, ValueError):
                misses += 1
                if misses >= tolerate:
                    raise InstanceError(
                        f"lost contact with the instance while waiting on {log} "
                        f"({tolerate} consecutive failures)"
                    )
                time.sleep(poll)
                continue
            if done in text:
                return text
            if fail in text:
                raise InstanceError(f"job failed. Tail of {log}:\n" + "\n".join(text.splitlines()[-25:]))
            time.sleep(poll)
        raise InstanceError(f"job did not finish within {timeout}s; see {log} on the instance")
