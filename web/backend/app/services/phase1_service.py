"""Phase 1 program-video service — DeepSeek (OpenAI-compatible) → program → render → bridge route.

Replaces the retired doc_planner + Manim path. For engine=auto/deterministic/generative:

1. Builds a prompt from the Re_0 phase1 Markdown specs (PHASE1_PROMPT.md, AGENTS.md) plus the
   user request.
2. Calls DeepSeek chat completions to generate the program source (app/index.html embedding
   ``LIVE_SCIENCE_META`` / ``LIVE_SCIENCE_BRIDGE``) and the subtitle track.
3. Writes them into a per-job run dir, renders the video (``render_video.mjs``), exports the
   bridge (``export_bridge.mjs``) and validates (``validate_outputs.py`` / ``validate_bridge.py``).
4. Reads ``bridge/manifest.json`` → route (``programmatic`` | ``realizable`` | ``hybrid``).
5. Returns the program video + manifest so the job manager can route to the model path.

On validation failure the errors are fed back to DeepSeek for a bounded number of fix iterations.

The DeepSeek client and the renderer are injectable so unit tests run without an API key or
Playwright/FFmpeg.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, JOBS_DIR, PHASE1_DIR

logger = logging.getLogger("uvicorn.error")

MAX_FIX_ITERATIONS = 3

# Files the generated program must produce (mirrors Re_0 phase1 output contract).
REQUIRED_SOURCE_FILES = ("app/index.html", "subtitles.srt")

_PROMPT_SYSTEM = (
    "You are the Live Science Phase 1 end-to-end programmatic teaching-video agent. "
    "Following the spec below, turn the user's concept or process into a publishable "
    "programmatic teaching video with in-frame subtitles."
)


def build_prompt(request_text: str) -> tuple[str, str]:
    """Assemble (system, user) messages from the Re_0 phase1 Markdown specs + request."""
    spec_dir = PHASE1_DIR
    parts: list[str] = []
    for name in ("PHASE1_PROMPT.md", "AGENTS.md"):
        p = spec_dir / name
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    specs = "\n\n".join(parts)
    user = (
        f"Strictly follow the Phase 1 spec below and output ONLY a single JSON object "
        f"(no Markdown code fence, no explanation) with two keys:\n"
        f"- `app`: the complete HTML program source (one file, inline CSS/JS) implementing the "
        f"deterministic time interface `window.LIVE_SCIENCE_META`, "
        f"`window.renderFrame(t, options)`, `window.__LIVE_SCIENCE_READY__`, and providing "
        f"`window.LIVE_SCIENCE_BRIDGE` with route / keyMoments / events;\n"
        f"- `subtitles`: the standard SRT subtitle track synced to the visuals.\n\n"
        f"IMPORTANT: all on-screen text, labels and subtitles MUST be written in English.\n\n"
        f"===== Phase 1 spec =====\n{specs}\n\n"
        f"===== User request =====\n{request_text}"
    )
    return _PROMPT_SYSTEM, user


def _extract_json(content: str) -> dict[str, Any]:
    """Parse an LLM JSON response, tolerating ```json fences."""
    text = content.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    return json.loads(text)


class Phase1Renderer:
    """Renders a generated program to video + bridge manifest using the Re_0 phase1 tools."""

    def __init__(self, phase1_dir: Path = PHASE1_DIR):
        self.phase1_dir = Path(phase1_dir)

    def render(self, run_dir: Path) -> dict[str, Any]:
        """Run render_video.mjs + export_bridge.mjs + validators; return artifact paths."""
        tools = self.phase1_dir / "tools"
        app_html = run_dir / "app" / "index.html"

        def run(*cmd: str) -> None:
            logger.info("phase1 tool: %s", " ".join(cmd))
            subprocess.run(cmd, cwd=str(run_dir), check=True, capture_output=True, text=True)

        # 1. render the program video + poster
        video = run_dir / "video.mp4"
        poster = run_dir / "poster.png"
        run(
            "node", str(tools / "render_video.mjs"),
            "--app", str(app_html), "--output", str(video), "--poster", str(poster),
        )

        # 2. export the bridge manifest (+ key-frame assets for realizable/hybrid)
        run("node", str(tools / "export_bridge.mjs"), "--app", str(app_html), "--output", str(run_dir / "bridge"))

        # 3. validate outputs + bridge
        py = sys.executable
        run(py, str(tools / "validate_outputs.py"), str(run_dir))
        run(py, str(tools / "validate_bridge.py"), str(run_dir))

        manifest_path = run_dir / "bridge" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        return {
            "video": video,
            "poster": poster,
            "subtitles": run_dir / "subtitles.srt",
            "manifest": manifest,
            "run_dir": run_dir,
        }


class Phase1Service:
    """Orchestrates one Phase 1 run: DeepSeek program generation → render → route."""

    def __init__(
        self,
        client_factory: Callable[[], Any] | None = None,
        renderer: Phase1Renderer | None = None,
    ):
        self._client_factory = client_factory or self._default_client
        self._renderer = renderer or Phase1Renderer()

    @staticmethod
    def _default_client() -> Any:
        from openai import OpenAI  # imported lazily so tests without the dep still import this module

        return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    def _generate_program(self, request_text: str, feedback: list[str] | None = None) -> dict[str, Any]:
        if not DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY not configured")
        system, user = build_prompt(request_text)
        if feedback:
            user += "\n\n===== Validation feedback for the previous attempt (fix these and re-output the FULL JSON) =====\n" + "\n---\n".join(feedback)
        client = self._client_factory()
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
        )
        content = resp.choices[0].message.content
        data = _extract_json(content)
        return data

    def run(self, job_id: str, text: str) -> dict[str, Any]:
        """Generate a program video for a job; returns renderer output (video + manifest)."""
        run_dir = JOBS_DIR / job_id / "phase1"
        (run_dir / "app").mkdir(parents=True, exist_ok=True)

        feedback: list[str] = []
        for attempt in range(MAX_FIX_ITERATIONS + 1):
            data = self._generate_program(text, feedback if attempt else None)
            app_html = str(data.get("app") or "")
            srt = str(data.get("subtitles") or "")
            if not app_html.strip():
                raise RuntimeError("Phase1 model returned no program source")
            (run_dir / "app" / "index.html").write_text(app_html, encoding="utf-8")
            (run_dir / "subtitles.srt").write_text(srt, encoding="utf-8")

            try:
                result = self._renderer.render(run_dir)
                result["attempts"] = attempt + 1
                return result
            except subprocess.CalledProcessError as exc:
                feedback.append(f"attempt {attempt + 1}: {exc.stderr or exc.stdout or exc}")
                logger.warning("phase1 validation failed (attempt %s): %s", attempt + 1, feedback[-1])

        raise RuntimeError("Phase 1 failed after repeated validation errors: " + feedback[-1])


def run_phase1(job_id: str, text: str) -> dict[str, Any]:
    """Module-level entry used by the job manager."""
    return Phase1Service().run(job_id, text)
