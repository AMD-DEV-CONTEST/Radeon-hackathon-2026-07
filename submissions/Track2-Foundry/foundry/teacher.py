"""Teacher access: an OpenAI-compatible llama-server, plus server lifecycle.

The teacher is whatever GGUF the config points at — Qwen3-4B stand-in on
the 4060, Qwen3-30B-A3B on the Radeon. Same server binary family, same
HTTP surface, so swapping teachers is a config edit.
"""

import subprocess
import time

import requests


def content_to_text(content) -> str:
    """Normalize message.content across llama.cpp builds.

    Pinned b9766 returns a plain string; newer builds may return the
    OpenAI-style list of typed parts ([{"type": "text", "text": ...}])
    or null. Everything downstream expects text.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                out.append(str(part.get("text", "")))
            else:
                out.append(str(part))
        return "".join(out)
    return str(content)


class TeacherClient:
    def __init__(self, base_url: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 512,
        json_mode: bool = False,
        seed: int | None = None,
        chat_template_kwargs: dict | None = None,
    ) -> str:
        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if chat_template_kwargs:
            payload["chat_template_kwargs"] = chat_template_kwargs
        if seed is not None:
            payload["seed"] = seed
        r = self.session.post(
            f"{self.base_url}/chat/completions", json=payload, timeout=self.timeout
        )
        r.raise_for_status()
        return content_to_text(r.json()["choices"][0]["message"]["content"])

    def chat_full(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> dict:
        """Chat completion returning the full message dict (content +
        tool_calls). Used by the agent loop."""
        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        r = self.session.post(
            f"{self.base_url}/chat/completions", json=payload, timeout=self.timeout
        )
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        msg["content"] = content_to_text(msg.get("content"))
        return msg

    def healthy(self) -> bool:
        try:
            r = self.session.get(self.base_url.removesuffix("/v1") + "/health", timeout=2)
            return r.status_code == 200
        except requests.RequestException:
            return False


def start_server(
    server_exe,
    gguf,
    port: int,
    n_gpu_layers: int,
    parallel: int,
    ctx_per_slot: int,
) -> subprocess.Popen:
    """Launch llama-server and block until it reports healthy."""
    from .llamacpp import resolve_binary
    server_exe = resolve_binary(server_exe, "llama-server")
    cmd = [
        str(server_exe),
        "-m", str(gguf),
        "--port", str(port),
        "-ngl", str(n_gpu_layers),
        "-np", str(parallel),
        "-c", str(parallel * ctx_per_slot),
        "--jinja",
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    client = TeacherClient(f"http://127.0.0.1:{port}/v1")
    # The 30B teacher takes ~2 min to load on the Radeon when the GGUF is
    # warm; from a cold or network-backed volume it can be slower. 180s
    # left almost no margin over the observed time.
    deadline = time.time() + 420
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"llama-server exited with code {proc.returncode} during startup "
                f"(cmd: {' '.join(cmd)})"
            )
        if client.healthy():
            return proc
        time.sleep(1.0)
    proc.kill()
    raise RuntimeError(f"llama-server did not become healthy within 420s on port {port}")


def stop_server(proc: subprocess.Popen):
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
