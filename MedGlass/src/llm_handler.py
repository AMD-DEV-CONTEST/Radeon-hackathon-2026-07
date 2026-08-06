"""SOAP note generation backends.

* ``ollama``      - local Ollama serve (e.g. ``qwen3.6:27b`` on localhost:11434).
                    Preferred local LLM path: no cloud, no GGUF download.
* ``openrouter``   - remote models via OpenRouter's OpenAI-compatible API.
                    Uses standard httpx/urllib transport with bearer auth.
* ``cli``          - llama.cpp ``llama-cli`` subprocess (ROCm / GPU). Target
                     deployment path from setup.sh.
* ``template``     - deterministic structured-note generator. No model needed.
                     Used automatically when no local model is reachable so the
                     full pipeline (transcript -> note) works everywhere. The
                     output is clearly a template, never fabricated clinical
                     detail: only facts found in the transcript are included.

Backend selection is driven by ``llm_backend`` in config:
  "auto" (default) -> Ollama if reachable, else llama.cpp CLI, else template.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

from config import CONFIG
from context_builder import build_prompt, build_chat_messages
from utils import MedGlassError

LOG = logging.getLogger("medglass.llm")

# Sections of the note we rebuild for the template backend.
_TEMPLATE = "**{section}:** {body}\n"


class LLMBackend:
    """Common interface for SOAP generation backends."""

    def generate(self, transcript: str,
                 visual_findings: list[dict] | None = None,
                 patient_name: str | None = None) -> str:
        raise NotImplementedError

    def generate_stream(self, transcript: str,
                        visual_findings: list[dict] | None = None,
                        patient_name: str | None = None):
        yield self.generate(transcript, visual_findings,
                            patient_name=patient_name)


class _CLILLM(LLMBackend):
    """llama.cpp ``llama-cli`` subprocess backend (ROCm on GPU)."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self._bin = Path(cfg["llama_bin"])
        self._model = Path(cfg["llama_model"])
        if not self._bin.exists():
            raise MedGlassError(
                f"llama.cpp binary not found at {self._bin}. Run setup.sh."
            )
        if not self._model.exists():
            raise MedGlassError(
                f"LLM model not found at {self._model}. "
                "Download Qwen3-8B GGUF into models/."
            )

    def _base_command(self, prompt_file: str) -> list[str]:
        return [
            str(self._bin),
            "--model", str(self._model),
            "--file", prompt_file,
            "--ctx-size", str(self.cfg["llama_ctx"]),
            "--threads", str(self.cfg["llama_threads"]),
            "--n-gpu-layers", str(self.cfg["llama_n_gpu_layers"]),
            "--temp", str(self.cfg["llama_temperature"]),
            "--n-predict", str(self.cfg["llama_max_tokens"]),
            "--no-display-prompt",
            "--verbose-prompt",
            "--reasoning", "off",
            "-no-cnv",
            "-st",
        ]

    def generate(self, transcript: str,
                 visual_findings: list[dict] | None = None,
                 patient_name: str | None = None) -> str:
        prompt = build_prompt(transcript, visual_findings,
                              patient_name=patient_name)
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False,
                encoding="utf-8") as fh:
            fh.write(prompt)
            prompt_path = fh.name
        try:
            out = self._run(prompt_path)
        finally:
            os.unlink(prompt_path)
        return self._clean_output(out, prompt)

    def generate_stream(self, transcript: str,
                        visual_findings: list[dict] | None = None,
                        patient_name: str | None = None):
        prompt = build_prompt(transcript, visual_findings,
                              patient_name=patient_name)
        prompt_lines = prompt.splitlines()
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False,
                encoding="utf-8") as fh:
            fh.write(prompt)
            prompt_path = fh.name
        try:
            proc = subprocess.Popen(
                self._base_command(prompt_path),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", bufsize=1,
            )
            # -st mode writes the banner + "> <prompt>" echo to stdout before
            # the completion; skip everything up to and including the echo,
            # then drop any further echoed prompt lines. Yield each line
            # verbatim (newline preserved) so "".join(tokens) reconstructs the
            # exact note, including line breaks between sections.
            started = False
            for line in proc.stdout:
                stripped = line.rstrip("\n")
                if not started:
                    if stripped.startswith("> "):
                        started = True
                    continue
                if self._is_echo_line(stripped, prompt_lines):
                    continue
                if self._is_noise(stripped):
                    continue
                yield line
            proc.wait(timeout=300)
        finally:
            os.unlink(prompt_path)

    def _run(self, prompt_path: str) -> str:
        try:
            proc = subprocess.run(
                self._base_command(prompt_path),
                capture_output=True, text=True, timeout=600, encoding="utf-8",
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            raise MedGlassError("llama.cpp timed out generating note")
        if proc.returncode != 0:
            raise MedGlassError(
                f"llama.cpp failed ({proc.returncode}): {proc.stderr[:2000]}")
        return proc.stdout

    @staticmethod
    def _is_echo_line(line: str, prompt_lines: list[str]) -> bool:
        """True when ``line`` is part of llama-cli's echoed prompt.

        Echoed lines are copied verbatim, but clipped lines get a literal
        "... (truncated)" suffix replacing the tail.
        """
        if line in prompt_lines:
            return True
        if line.endswith("... (truncated)"):
            prefix = line[: -len("... (truncated)")].rstrip()
            return any(pl.startswith(prefix) for pl in prompt_lines)
        return False

    @staticmethod
    def _is_noise(line: str) -> bool:
        """True for banner, timing and session-control lines to drop."""
        s = line.strip()
        if not s:
            return True
        if s in ("Exiting...", "[end of text]"):
            return True
        if s.startswith("["):
            return True
        if line.startswith(("llama_", "print_info:", "system_info:",
                            "sampler_", "log ", "main:")):
            return True
        return False

    @staticmethod
    def _clean_output(text: str, prompt: str | None = None) -> str:
        # In -st mode llama-cli renders the prompt as "> <first line>" plus a
        # truncated prefix of the remaining prompt lines, then the completion.
        # Everything before the last "> " line is banner noise.
        lines = text.splitlines()
        last_marker = None
        for i, line in enumerate(lines):
            if line.startswith("> "):
                last_marker = i
        if last_marker is not None:
            lines = lines[last_marker + 1:]

        # Drop the echoed prefix of the prompt, stopping at the first line
        # that is not part of the prompt.
        prompt_lines = list(prompt.splitlines()) if prompt else []
        while lines:
            if lines[0] == "" or _CLILLM._is_echo_line(lines[0], prompt_lines):
                lines = lines[1:]
                continue
            break

        return "\n".join(
            line for line in lines if not _CLILLM._is_noise(line)).strip()


class _OllamaLLM(LLMBackend):
    """Local Ollama backend (qwen3.6:27b served on localhost:11434).

    Talks to Ollama's REST API so the LLM runs 100% on this machine — no
    cloud inference, no separate GGUF download.
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.url = cfg.get("ollama_url", "http://localhost:11434")
        self.model = cfg.get("ollama_model", "qwen3.6:27b")
        self._verify()

    def _verify(self) -> None:
        try:
            req = urllib.request.Request(f"{self.url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except OSError as exc:
            raise MedGlassError(
                f"Ollama unreachable at {self.url}: {exc}. "
                "Start it with: ollama serve")
        names = {m.get("name") for m in data.get("models", [])}
        if self.model not in names:
            raise MedGlassError(
                f"Model {self.model!r} not in Ollama. Run: ollama pull {self.model}")
        LOG.info("LLM backend: ollama %s (local)", self.model)

    def _options(self) -> dict:
        return {
            "num_ctx": self.cfg.get("ollama_num_ctx", 8192),
            "temperature": self.cfg["llama_temperature"],
            "num_predict": self.cfg.get("ollama_num_predict", 2048),
        }

    def generate(self, transcript: str,
                 visual_findings: list[dict] | None = None,
                 patient_name: str | None = None) -> str:
        messages = build_chat_messages(transcript, visual_findings,
                                       patient_name=patient_name)
        return self._chat(messages)

    def generate_stream(self, transcript: str,
                        visual_findings: list[dict] | None = None,
                        patient_name: str | None = None):
        yield self.generate(transcript, visual_findings, patient_name=patient_name)

    def _chat(self, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self._options(),
        }
        req = urllib.request.Request(
            f"{self.url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise MedGlassError(
                f"Ollama error ({exc.code}): {exc.read().decode('utf-8', 'ignore')[:500]}")
        except OSError as exc:
            raise MedGlassError(f"Ollama request failed: {exc}")
        if data.get("error"):
            raise MedGlassError(f"Ollama error: {data['error']}")
        return (data.get("message", {}).get("content") or "").strip()


class _TemplateLLM(LLMBackend):
    """Deterministic no-model fallback.

    Extracts only patient-stated facts and visual findings from the
    transcript so the note is a faithful summary, not a fabrication.
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        LOG.info("LLM backend: template (no llama.cpp binary present)")

    # -- extraction helpers -------------------------------------------------

    @staticmethod
    def _speaker_lines(transcript: str) -> list[str]:
        lines = []
        for raw in transcript.splitlines():
            line = raw.strip()
            if not line:
                continue
            # Normalise "Doctor: \"...\"" / "Patient: \"...\"" / "Patient: ..."
            line = line.replace("\\\"", '"').strip('" ')
            if line.lower().startswith(("doctor", "patient", "nurse", "dr")):
                # keep the speaker label
                lines.append(line)
            elif line:
                lines.append(line)
        return lines

    @staticmethod
    def _by_speaker(transcript: str) -> dict[str, list[str]]:
        bucket: dict[str, list[str]] = {"doctor": [], "patient": []}
        current = "doctor"
        for raw in transcript.splitlines():
            line = raw.strip().strip('"').strip()
            if not line:
                continue
            low = line.lower()
            if low.startswith(("patient", "pt")):
                current = "patient"
                body = line.split(":", 1)[1].strip().strip('"') if ":" in line else line
            elif low.startswith(("doctor", "dr", "nurse")):
                current = "doctor"
                body = line.split(":", 1)[1].strip().strip('"') if ":" in line else line
            else:
                body = line
            if body:
                bucket[current].append(body)
        return bucket

    def generate(self, transcript: str,
                 visual_findings: list[dict] | None = None) -> str:
        spk = self._by_speaker(transcript)
        patient = " ".join(spk["patient"])
        doctor = " ".join(spk["doctor"])
        visual = self._describe_visual(visual_findings)

        subjective = self._subjective(patient)
        objective = self._objective(doctor, visual)
        assessment = self._assessment(patient, doctor)
        plan = self._plan(doctor, patient)

        note = (
            _TEMPLATE.format(section="Subjective", body=subjective)
            + _TEMPLATE.format(section="Objective", body=objective)
            + _TEMPLATE.format(section="Assessment", body=assessment)
            + _TEMPLATE.format(section="Plan", body=plan)
        ).strip()
        return note

    @staticmethod
    def _describe_visual(visual_findings: list[dict] | None) -> str:
        if not visual_findings:
            return "No photos or detections captured."
        parts = []
        for v in visual_findings:
            detail = v.get("detail", "").strip()
            if detail:
                parts.append(f"{v.get('kind', 'observation')}: {detail}")
            else:
                parts.append(f"{v.get('kind', 'observation')} observed")
        return "; ".join(parts)

    @staticmethod
    def _subjective(patient: str) -> str:
        if not patient:
            return "[ ] No patient-reported history captured in transcript."
        return f"Patient reports: {patient}"

    @staticmethod
    def _objective(doctor: str, visual: str) -> str:
        findings = []
        if doctor:
            findings.append(f"Clinician notes: {doctor}")
        findings.append(f"Visual: {visual}")
        return " ".join(findings)

    @staticmethod
    def _assessment(patient: str, doctor: str) -> str:
        markers = ["diagnos", "likely", "suggest", "think", "assessment",
                   "impression", "concern", "suspect", "favor", "favour"]
        combined = f"{doctor} {patient}".lower()
        hits = [m for m in markers if m in combined]
        if hits:
            return f"Clinical impression present in conversation (\"{', '.join(sorted(set(hits)))}\"). [Template backend — confirm with clinician]"
        return "[ ] No explicit assessment stated in transcript."

    @staticmethod
    def _plan(doctor: str, patient: str) -> str:
        markers = ["prescribe", "medication", "refill", "start", "follow",
                   "return", "refer", "recommend", "take", "dose", "mg"]
        combined = f"{doctor} {patient}".lower()
        hits = [m for m in markers if m in combined]
        if hits:
            return (f"Treatment discussion present (\"{', '.join(sorted(set(hits)))}\"). "
                    "Extract prescription/follow-up details from transcript. [Template backend]")
        return "[ ] No explicit plan stated in transcript."


class _OpenRouterLLM(LLMBackend):
    """Remote LLM via OpenRouter's OpenAI-compatible API.

    Accepts any model available on OpenRouter. Model identifier is set in
    config as ``openrouter_model`` (e.g. ``anthropic/claude-3.5-sonnet`` or
    ``~openai/gpt-latest``). Authentication via bearer token in
    ``openrouter_api_key`` or the environment variable
    ``MEDGLASS_OPENROUTER_API_KEY``.
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.url = "https://openrouter.ai/api/v1"
        self.model = cfg.get(
            "openrouter_model", cfg.get("ollama_model", "~openai/gpt-latest")
        )
        self.api_key = cfg.get(
            "openrouter_api_key", os.environ.get("OPENROUTER_API_KEY", "")
        )
        if not self.api_key:
            LOG.warning(
                "openrouter backend selected but no API key set. "
                "Set config key 'openrouter_api_key' or env OPENROUTER_API_KEY."
            )

    def _options(self) -> dict:
        return {
            "max_tokens": self.cfg.get("ollama_num_predict", 2048),
            "temperature": self.cfg["llama_temperature"],
        }

    def generate(self, transcript: str,
                 visual_findings: list[dict] | None = None,
                 patient_name: str | None = None) -> str:
        messages = build_chat_messages(transcript, visual_findings,
                                       patient_name=patient_name)
        return self._chat(messages)

    def generate_stream(self, transcript: str,
                        visual_findings: list[dict] | None = None,
                        patient_name: str | None = None):
        yield self.generate(transcript, visual_findings, patient_name=patient_name)

    def _chat(self, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            **self._options(),
        }
        req = urllib.request.Request(
            f"{self.url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": self.cfg.get("openrouter_referer", "http://localhost:8100"),
                "X-Title": self.cfg.get("openrouter_title", "MedGlass"),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "ignore")[:1000]
            raise MedGlassError(
                f"OpenRouter error ({exc.code}): {body}"
            )
        except OSError as exc:
            raise MedGlassError(f"OpenRouter request failed: {exc}")
        if "error" in data:
            raise MedGlassError(f"OpenRouter API error: {data['error']}")
        content = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        return content


def build_backend(cfg: dict | None = None) -> LLMBackend:
    cfg = cfg or CONFIG
    mode = cfg.get("llm_backend", "auto")
    if mode == "ollama":
        return _OllamaLLM(cfg)
    if mode == "openrouter":
        return _OpenRouterLLM(cfg)
    if mode == "cli":
        return _CLILLM(cfg)
    if mode == "template":
        return _TemplateLLM(cfg)
    # auto: local Ollama first, then llama.cpp CLI, then template.
    try:
        return _OllamaLLM(cfg)
    except MedGlassError:
        pass
    if Path(cfg["llama_bin"]).exists():
        LOG.info("LLM backend: llama.cpp cli")
        return _CLILLM(cfg)
    LOG.info("LLM backend: template (no local model)")
    return _TemplateLLM(cfg)


class LLMHandler:
    """Facade kept for API compatibility with existing callers."""

    def __init__(self, cfg: dict | None = None,
                 backend: LLMBackend | None = None) -> None:
        self.cfg = cfg or CONFIG
        self.backend = backend or build_backend(self.cfg)

    @property
    def _bin(self) -> Path:
        return Path(self.cfg["llama_bin"])

    def generate(self, transcript: str,
                 visual_findings: list[dict] | None = None,
                 patient_name: str | None = None) -> str:
        return self.backend.generate(transcript, visual_findings,
                                     patient_name=patient_name)

    def generate_stream(self, transcript: str,
                        visual_findings: list[dict] | None = None,
                        patient_name: str | None = None):
        yield from self.backend.generate_stream(transcript, visual_findings,
                                                patient_name=patient_name)
