"""
Find it — FastAPI daemon for the "flashback-anywhere" video-audio-search project.

It helps users find things by recording and uploading videos, then analysing
them: videos are catalogued, transcoded, and processed into frame descriptions
and audio transcriptions that can be searched or queried through an agentic
chat interface.

Step-1 demo: a basic video upload + catalogue service.

Features
--------
- Upload a video (mp4 / mpegts / common container) together with metadata entries:
    * name        (optional, may be blank)
    * location    (required; pick an existing place or type a new one)
    * record_time (defaults to "now", or a user supplied value)
    * rotation    (0/90/180/270, display transform chosen in the UI)
    * mirror      (horizontal flip chosen in the UI)
- On upload the file is stored to disk and probed with **ffprobe** to detect:
    * fps (average frame rate)
    * whether the video carries an audio stream
    * duration / resolution / container
- **Previews are rendered by ffmpeg on the backend** (a single JPEG frame), so
  even formats the browser cannot play natively (e.g. MPEG-TS) get a preview.
  Rotation / mirroring are applied by ffmpeg in the preview image — the stored
  video file itself is never transcoded/transposed; we only keep the transform
  as metadata.
- A staging area lets the front-end fetch an ffmpeg preview (and re-render it on
  rotate/mirror) for a file the user has selected but not yet uploaded.
- List / retrieve uploaded videos and their properties, sortable by
  location, upload time or name.

Run
---
    uvicorn main:app --host 0.0.0.0 --port 8090
or use the provided setup.sh / launch.sh helpers.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import agentic
from ai_clients import (
    agent_llm_client,
    asr_client,
    convert_audio_to_wav,
    extract_audio_for_interval,
    extract_frames_for_interval,
    get_ai_config,
    get_agent_config,
    vlm_client,
)

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
def _setup_logging() -> logging.Logger:
    log = logging.getLogger("video_upload")
    if not log.handlers:
        handler = logging.StreamHandler()
        level = os.environ.get("VIDEO_LOG_LEVEL", "INFO").upper()
        handler.setFormatter(logging.Formatter(
            "[video_upload] %(asctime)s %(levelname)s %(message)s"
        ))
        log.addHandler(handler)
        log.setLevel(getattr(logging, level, logging.INFO))
        log.propagate = False
    return log


log = _setup_logging()

# --------------------------------------------------------------------------- #
# Paths / constants
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
STAGING_DIR = UPLOAD_DIR / "_staging"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "videos.db"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STAGING_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Staged (selected-but-not-uploaded) files are swept after this many seconds.
STAGING_TTL_SECONDS = 3600

# Containers we accept for upload. Anything else -> 415.
ALLOWED_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v",
    ".ts", ".mts", ".m2ts",  # MPEG-TS (e.g. OBS / broadcast captures)
}

# Sort keys exposed by /videos (validated against this whitelist).
SORTABLE_COLUMNS = {"location", "upload_time", "name", "record_time"}

# Make sure MPEG-TS streams get a video MIME type (some Python builds map
# ".ts" to a non-video type, which would break <video> preview/playback).
for _ext in (".ts", ".mts", ".m2ts"):
    mimetypes.add_type("video/mp2t", _ext)

# Maximum concurrent jobs per task type (env configurable)
MAX_TRANSCODE_JOBS = int(os.environ.get("MAX_TRANSCODE_JOBS", "1"))
MAX_TRANSCRIBE_JOBS = int(os.environ.get("MAX_TRANSCRIBE_JOBS", "1"))

# --------------------------------------------------------------------------- #
# FTS5 tokenizer detection
# --------------------------------------------------------------------------- #

def _detect_fts5_tokenizer() -> str:
    """Return 'trigram' if the FTS5 trigram tokenizer is available, else 'simple'."""
    try:
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.execute(
                "CREATE VIRTUAL TABLE _test_fts5 USING fts5(text, tokenize='trigram')"
            )
            return "trigram"
    except sqlite3.OperationalError:
        return "simple"


FTS5_TOKENIZER = _detect_fts5_tokenizer()

# --------------------------------------------------------------------------- #
# Database (sqlite3 from the stdlib — no extra dependency)
# --------------------------------------------------------------------------- #

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id           TEXT PRIMARY KEY,
    stored_name  TEXT NOT NULL,          -- filename on disk
    orig_name    TEXT NOT NULL,          -- original upload filename
    name         TEXT,                   -- user entry (may be blank)
    location     TEXT NOT NULL,          -- user entry (required)
    record_time  TEXT NOT NULL,          -- ISO-8601; user entry or "now"
    upload_time  TEXT NOT NULL,          -- ISO-8601, set by the server
    rotation     INTEGER NOT NULL DEFAULT 0,   -- 0/90/180/270, display-only
    mirror       INTEGER NOT NULL DEFAULT 0,   -- 0/1, display-only
    -- ffprobe-derived properties (nullable until probed)
    fps          REAL,
    has_audio    INTEGER,
    duration     REAL,
    width        INTEGER,
    height       INTEGER,
    container    TEXT,
    size_bytes   INTEGER,
    -- stateful processing
    status                TEXT NOT NULL DEFAULT 'queued',  -- queued|transcoding|transcoded|failed
    transcription_status  TEXT NOT NULL DEFAULT 'untranscribed', -- untranscribed|transcripting|transcribed|failed
    transcription_progress REAL DEFAULT 0.0,                  -- 0..100
    transcode_progress    REAL DEFAULT 0.0,                   -- 0..100
    transcode_error       TEXT
);
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


TRANSCRIPTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS frame_descriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    description     TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_frames_video_ts
    ON frame_descriptions(video_id, timestamp);

CREATE TABLE IF NOT EXISTS audio_transcriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        TEXT NOT NULL,
    segment_index   INTEGER NOT NULL,
    start_seconds   REAL NOT NULL,
    end_seconds     REAL NOT NULL,
    text            TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_audio_video_segment
    ON audio_transcriptions(video_id, segment_index);
CREATE INDEX IF NOT EXISTS idx_audio_video_time
    ON audio_transcriptions(video_id, start_seconds, end_seconds);

CREATE TABLE IF NOT EXISTS transcription_jobs (
    id                TEXT PRIMARY KEY,
    video_id          TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    status            TEXT NOT NULL DEFAULT 'pending',
    total_chunks      INTEGER,
    current_chunk_index INTEGER DEFAULT -1,
    error_message     TEXT,
    options           TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcription_job_chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL REFERENCES transcription_jobs(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    start_seconds   REAL NOT NULL,
    end_seconds     REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    completed_at    TEXT,
    UNIQUE(job_id, chunk_index)
);
"""


def _create_fts_tables(conn: sqlite3.Connection) -> None:
    """Create FTS5 external-content tables and sync triggers."""
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_frames USING fts5(
            description,
            content='frame_descriptions',
            content_rowid='id',
            tokenize='{FTS5_TOKENIZER}'
        )
        """
    )
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_audio USING fts5(
            text,
            content='audio_transcriptions',
            content_rowid='id',
            tokenize='{FTS5_TOKENIZER}'
        )
        """
    )
    conn.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS fts_frames_ai AFTER INSERT ON frame_descriptions BEGIN
            INSERT INTO fts_frames(rowid, description) VALUES (new.id, new.description);
        END;
        CREATE TRIGGER IF NOT EXISTS fts_frames_ad AFTER DELETE ON frame_descriptions BEGIN
            INSERT INTO fts_frames(fts_frames, rowid, description) VALUES('delete', old.id, old.description);
        END;

        CREATE TRIGGER IF NOT EXISTS fts_audio_ai AFTER INSERT ON audio_transcriptions BEGIN
            INSERT INTO fts_audio(rowid, text) VALUES (new.id, new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS fts_audio_ad AFTER DELETE ON audio_transcriptions BEGIN
            INSERT INTO fts_audio(fts_audio, rowid, text) VALUES('delete', old.id, old.text);
        END;
        """
    )


def init_db() -> None:
    with closing(get_db()) as conn, conn:
        conn.execute(SCHEMA)
        # Lightweight migration for catalogues created before rotation/mirror
        # existed: add the columns if they are missing.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(videos)")}
        if "rotation" not in cols:
            conn.execute(
                "ALTER TABLE videos ADD COLUMN rotation INTEGER NOT NULL DEFAULT 0"
            )
        if "mirror" not in cols:
            conn.execute(
                "ALTER TABLE videos ADD COLUMN mirror INTEGER NOT NULL DEFAULT 0"
            )
        if "status" not in cols:
            conn.execute("ALTER TABLE videos ADD COLUMN status TEXT NOT NULL DEFAULT 'queued'")
            # Existing videos from before stateful processing were already transcoded.
            conn.execute("UPDATE videos SET status = 'transcoded'")
        if "transcription_status" not in cols:
            conn.execute("ALTER TABLE videos ADD COLUMN transcription_status TEXT NOT NULL DEFAULT 'untranscribed'")
        if "transcription_progress" not in cols:
            conn.execute("ALTER TABLE videos ADD COLUMN transcription_progress REAL DEFAULT 0.0")
        if "transcode_progress" not in cols:
            conn.execute("ALTER TABLE videos ADD COLUMN transcode_progress REAL DEFAULT 0.0")
        if "transcode_error" not in cols:
            conn.execute("ALTER TABLE videos ADD COLUMN transcode_error TEXT")
        conn.executescript(TRANSCRIPTION_SCHEMA)
        _create_fts_tables(conn)
        agentic.create_agent_tables(conn)


# --------------------------------------------------------------------------- #
# ffprobe helpers
# --------------------------------------------------------------------------- #

def _run_ffprobe(path: Path) -> dict[str, Any]:
    """Return the raw ffprobe JSON for *path* (raises on failure)."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries",
        "stream=codec_type,avg_frame_rate,width,height:"
        "format=duration,format_name,size",
        "-of", "json",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=60
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed: {exc.stderr.strip()}") from exc
    return json.loads(proc.stdout or "{}")


def _fraction_to_float(value: Optional[str]) -> Optional[float]:
    """Convert an ffprobe rate like '30000/1001' (or '30') to a float."""
    if not value or value in ("0/0", "N/A"):
        return None
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            den_f = float(den)
            return round(float(num) / den_f, 3) if den_f else None
        except ValueError:
            return None
    try:
        return round(float(value), 3)
    except ValueError:
        return None


def probe_video(path: Path) -> dict[str, Any]:
    """Extract the properties we care about from a media file."""
    raw = _run_ffprobe(path)

    streams = raw.get("streams", []) or []
    fmt = raw.get("format", {}) or {}

    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"), None
    )
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    fps = _fraction_to_float(video_stream.get("avg_frame_rate")) if video_stream else None
    duration = None
    if fmt.get("duration") not in (None, "N/A"):
        try:
            duration = round(float(fmt["duration"]), 3)
        except ValueError:
            duration = None

    size_bytes = None
    if fmt.get("size") not in (None, "N/A"):
        try:
            size_bytes = int(fmt["size"])
        except ValueError:
            size_bytes = None

    return {
        "fps": fps,
        "has_audio": has_audio,
        "duration": duration,
        "width": video_stream.get("width") if video_stream else None,
        "height": video_stream.get("height") if video_stream else None,
        "container": fmt.get("format_name"),
        "size_bytes": size_bytes,
    }


# --------------------------------------------------------------------------- #
# ffmpeg preview rendering
# --------------------------------------------------------------------------- #

def _transform_filter(rotation: int, mirror: bool) -> str:
    """Build the ffmpeg -vf chain for the requested display transform.

    Mirrors the CSS `rotate(<deg>) scaleX(<-1>)` semantics used in the UI:
    the mirror (hflip) is applied first, then the rotation.
    """
    vf: list[str] = []
    if mirror:
        vf.append("hflip")
    r = rotation % 360
    if r == 90:
        vf.append("transpose=1")            # 90° clockwise
    elif r == 180:
        vf.append("transpose=1,transpose=1")
    elif r == 270:
        vf.append("transpose=2")            # 90° counter-clockwise
    return ",".join(vf) if vf else "null"


def make_preview_image(
    src: Path, rotation: int = 0, mirror: bool = False, ts: float = 0.5
) -> bytes:
    """Render a single JPEG frame of *src* at *ts* seconds with ffmpeg.

    Applies the rotation/mirror display transform. Returns raw JPEG bytes.
    """
    cmd = [
        "ffmpeg",
        "-v", "error",
        "-ss", f"{max(ts, 0.0):.3f}",
        "-i", str(src),
        "-vf", _transform_filter(rotation, mirror),
        "-frames:v", "1",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg not found on PATH") from exc
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"ffmpeg preview failed: {err}")
    return proc.stdout


# --------------------------------------------------------------------------- #
# MP4 transcoding (bake rotation/mirror into pixels for browser compat)
# --------------------------------------------------------------------------- #


def transcode_to_mp4(
    src: Path,
    dest: Path,
    rotation: int = 0,
    mirror: bool = False,
    has_audio: bool = True,
) -> None:
    """Transcode *src* to H.264+AAC MP4 at *dest*.

    Rotation / mirror are baked into the pixel data rather than stored as
    metadata-only, ensuring the output plays correctly in any browser.
    """
    vf = _transform_filter(rotation, mirror)
    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts",
        "-i", str(src),
    ]
    if vf != "null":
        cmd.extend(["-vf", f"{vf},format=yuv420p"])
    else:
        cmd.extend(["-vf", "format=yuv420p"])
    cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-movflags", "+faststart"])
    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    else:
        cmd.append("-an")
    cmd.append(str(dest))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg not found on PATH") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"transcode to mp4 failed: {proc.stderr.strip()}")


# --------------------------------------------------------------------------- #
# Staging (selected-but-not-yet-uploaded files)
# --------------------------------------------------------------------------- #

def _sweep_staging() -> None:
    now = time.time()
    for p in STAGING_DIR.glob("*"):
        try:
            if p.is_file() and now - p.stat().st_mtime > STAGING_TTL_SECONDS:
                p.unlink(missing_ok=True)
        except OSError:
            pass


def _staged_path(stage_id: str) -> Optional[Path]:
    if not stage_id or any(c in stage_id for c in "/\\.."):
        return None
    return next(STAGING_DIR.glob(f"{stage_id}.*"), None)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

_transcribe_worker_task: asyncio.Task | None = None
_transcode_worker_task: asyncio.Task | None = None
_running_transcode_tasks: dict[str, asyncio.Task] = {}
_running_transcode_procs: dict[str, Any] = {}
_running_transcribe_jobs: dict[str, str] = {}  # video_id -> job_id
_cancelled_video_ids: set[str] = set()          # videos being deleted; workers abort gracefully
_transcode_sem = asyncio.Semaphore(MAX_TRANSCODE_JOBS)
_transcribe_sem = asyncio.Semaphore(MAX_TRANSCRIBE_JOBS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    # Reset orphaned transcription jobs from a previous crash.
    with closing(get_db()) as conn:
        conn.execute(
            "UPDATE transcription_jobs SET status = 'queued', updated_at = ?"
            " WHERE status = 'running'",
            (_now_iso(),),
        )
        conn.execute(
            "UPDATE transcription_job_chunks SET status = 'pending',"
            " error_message = NULL, completed_at = NULL"
            " WHERE status = 'running'",
        )
        # Reset videos that were being transcoded when the daemon died.
        conn.execute(
            "UPDATE videos SET status = 'queued', transcode_progress = 0.0,"
            " transcode_error = NULL WHERE status = 'transcoding'",
        )
        conn.commit()

    # Startup: clean up orphaned disk files (files with no DB entry).
    cleanup_orphan_disk_files()
    # Clean up stale staging dirs.
    _cleanup_stale_staging()

    # Start background workers.
    global _transcribe_worker_task, _transcode_worker_task
    _transcribe_worker_task = asyncio.create_task(_transcription_worker_loop())
    _transcode_worker_task = asyncio.create_task(_transcode_worker_loop())

    transcode_cleanup_tmp = _cleanup_orphan_transcode_tmp()

    yield

    # Cancel running transcodes.
    for vid, task in list(_running_transcode_tasks.items()):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    # Kill any orphaned ffmpeg processes.
    for vid, proc in list(_running_transcode_procs.items()):
        try:
            proc.terminate()
            await proc.wait()
        except (ProcessLookupError, Exception):
            pass
    _running_transcode_tasks.clear()
    _running_transcode_procs.clear()

    if _transcode_worker_task:
        _transcode_worker_task.cancel()
        try:
            await _transcode_worker_task
        except asyncio.CancelledError:
            pass

    if _transcribe_worker_task:
        _transcribe_worker_task.cancel()
        try:
            await _transcribe_worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Find it", version="0.1.0", lifespan=lifespan)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["has_audio"] = bool(d.get("has_audio"))
    d["mirror"] = bool(d.get("mirror"))
    d["url"] = f"/media/{d['id']}"
    d["preview_url"] = f"/videos/{d['id']}/preview"
    return d


def _check_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"unsupported type: {suffix}")
    return suffix


def _save_upload(file: UploadFile, dest: Path) -> None:
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)


# --------------------------------------------------------------------------- #
# Transcription models
# --------------------------------------------------------------------------- #

class FrameImport(BaseModel):
    timestamp: float = Field(..., ge=0)
    description: str = Field(..., min_length=1)


class AudioImport(BaseModel):
    index: int = Field(..., ge=1)
    start: str = ""
    end: str = ""
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., ge=0)
    text: str = Field(..., min_length=1)

    @field_validator("end_seconds")
    @classmethod
    def end_after_start(cls, v: float, info) -> float:
        start = info.data.get("start_seconds", 0.0)
        if v < start:
            raise ValueError("end_seconds must be >= start_seconds")
        return v


class TranscriptionImportPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    frame_descriptions: list[FrameImport] = Field(default_factory=list)
    transcriptions: list[AudioImport] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Search helpers
# --------------------------------------------------------------------------- #

def _fts_safe_query(q: str) -> str:
    """Turn a user query into an FTS5 MATCH phrase (AND of quoted tokens)."""
    tokens = [t for t in q.strip().split() if t]
    if not tokens:
        return ""
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in tokens)


def _wrap_mark(text: str, qlo: str, idx: int, radius: int) -> str:
    """Build an excerpt around *idx* with the matched substring wrapped in <mark>."""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(qlo) + radius)
    snippet = text[start:end]
    rel = idx - start
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return (
        prefix
        + html.escape(snippet[:rel])
        + "<mark>"
        + html.escape(snippet[rel : rel + len(qlo)])
        + "</mark>"
        + html.escape(snippet[rel + len(qlo) :])
        + suffix
    )


def _highlight_text(text: str, q: str, radius: int = 80) -> str:
    """Return an HTML excerpt of *text* highlighting the first match of *q*."""
    if not text:
        return ""
    q = q.strip()
    if not q:
        return html.escape(text[: radius * 2])
    lo = text.lower()
    qlo = q.lower()
    idx = lo.find(qlo)
    if idx != -1:
        return _wrap_mark(text, qlo, idx, radius)
    # Full phrase not contiguous: highlight the first present token.
    for token in q.split():
        tlo = token.lower()
        tidx = lo.find(tlo)
        if tidx != -1:
            return _wrap_mark(text, tlo, tidx, radius)
    return html.escape(text[: radius * 2])


_SearchSource = Literal["frame", "audio"]


def _collect_fts(
    conn: sqlite3.Connection,
    safe_q: str,
    source: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Collect FTS5 matches for the quoted query."""
    results: list[dict[str, Any]] = []
    specs: list[tuple[_SearchSource, str, str, str, str, str]] = []
    if source in (None, "frame"):
        specs.append(
            ("frame", "fts_frames", "frame_descriptions", "description", "timestamp", "timestamp")
        )
    if source in (None, "audio"):
        specs.append(
            ("audio", "fts_audio", "audio_transcriptions", "text", "start_seconds", "end_seconds")
        )

    for src_name, fts, content, text_col, ts_col, end_col in specs:
        sql = f"""
            SELECT c.id AS row_id, c.video_id,
                   c.{ts_col} AS ts, c.{end_col} AS ts_end,
                   c.{text_col} AS text,
                   snippet({fts}, 0, '<mark>', '</mark>', '...', 64) AS excerpt,
                   rank
            FROM {fts}
            JOIN {content} c ON c.id = {fts}.rowid
            WHERE {fts} MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        for r in conn.execute(sql, (safe_q, limit)):
            results.append(
                {
                    "source": src_name,
                    "row_id": r["row_id"],
                    "video_id": r["video_id"],
                    "timestamp": float(r["ts"]),
                    "end_timestamp": float(r["ts_end"]) if src_name == "audio" else None,
                    "text": r["text"],
                    "excerpt": r["excerpt"],
                    "rank": float(r["rank"]),
                }
            )
    return results


def _collect_instr(
    conn: sqlite3.Connection,
    q: str,
    source: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Collect substring matches using INSTR (AND semantics across tokens)."""
    results: list[dict[str, Any]] = []
    tokens = [t for t in q.strip().split() if t]
    if not tokens:
        return results

    specs: list[tuple[_SearchSource, str, str, str, str]] = []
    if source in (None, "frame"):
        specs.append(("frame", "frame_descriptions", "description", "timestamp", "timestamp"))
    if source in (None, "audio"):
        specs.append(("audio", "audio_transcriptions", "text", "start_seconds", "end_seconds"))

    for src_name, content, text_col, ts_col, end_col in specs:
        where = " AND ".join(
            f"INSTR(LOWER(c.{text_col}), LOWER(?)) > 0" for _ in tokens
        )
        sql = f"""
            SELECT c.id AS row_id, c.video_id,
                   c.{ts_col} AS ts, c.{end_col} AS ts_end,
                   c.{text_col} AS text
            FROM {content} c
            WHERE {where}
            LIMIT ?
        """
        params = list(tokens) + [limit]
        for r in conn.execute(sql, params):
            results.append(
                {
                    "source": src_name,
                    "row_id": r["row_id"],
                    "video_id": r["video_id"],
                    "timestamp": float(r["ts"]),
                    "end_timestamp": float(r["ts_end"]) if src_name == "audio" else None,
                    "text": r["text"],
                    "excerpt": _highlight_text(r["text"], q),
                    "rank": 1_000_000.0,
                }
            )
    return results


def _search_transcriptions(
    conn: sqlite3.Connection,
    q: str,
    source: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Mixed FTS5 + substring search across frame/audio transcriptions."""
    hits: dict[tuple[str, int], dict[str, Any]] = {}

    safe_q = _fts_safe_query(q)
    if safe_q:
        for hit in _collect_fts(conn, safe_q, source, limit * 2):
            hits[(hit["source"], hit["row_id"])] = hit

    for hit in _collect_instr(conn, q, source, limit * 2):
        key = (hit["source"], hit["row_id"])
        if key not in hits:
            hits[key] = hit

    enriched: list[dict[str, Any]] = []
    for hit in hits.values():
        video = conn.execute(
            "SELECT * FROM videos WHERE id = ?", (hit["video_id"],)
        ).fetchone()
        if video is None:
            continue
        video_dict = _row_to_dict(video)
        duration = video_dict.get("duration") or 0.0
        ts = hit["timestamp"]
        context_start = max(0.0, ts - 3.0)
        context_end = ts + 3.0
        if duration:
            context_end = min(context_end, duration)

        enriched.append(
            {
                "source": hit["source"],
                "row_id": hit["row_id"],
                "timestamp": ts,
                "end_timestamp": hit.get("end_timestamp"),
                "context_start": context_start,
                "context_end": context_end,
                "text": hit["text"],
                "excerpt": hit["excerpt"],
                "rank": hit["rank"],
                "video": video_dict,
            }
        )

    # FTS rank ascending is better; tie-break by most recently uploaded.
    enriched.sort(key=lambda r: (r["rank"], r["video"]["upload_time"] or ""), reverse=False)
    return enriched[:limit]


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.post("/probe")
async def probe_only(file: UploadFile = File(...)) -> dict[str, Any]:
    """Probe an uploaded file for fps / audio WITHOUT storing it."""
    suffix = _check_suffix(file.filename or "")
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            _save_upload(file, tmp_path)
        return probe_video(tmp_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


@app.post("/stage", status_code=201)
async def stage_video(file: UploadFile = File(...)) -> dict[str, Any]:
    """Store a selected file in the staging area and probe it.

    Returns a stage_id used to fetch ffmpeg-rendered previews (which update as
    the user rotates/mirrors) before the file is actually uploaded.
    """
    _sweep_staging()
    suffix = _check_suffix(file.filename or "")

    stage_id = uuid.uuid4().hex
    dest = STAGING_DIR / f"{stage_id}{suffix}"
    _save_upload(file, dest)
    try:
        props = probe_video(dest)
    except RuntimeError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"probe failed: {exc}")

    return {"stage_id": stage_id, "preview_url": f"/stage/{stage_id}/preview", **props}


@app.get("/stage/{stage_id}/preview")
def stage_preview(
    stage_id: str,
    rotation: int = Query(0),
    mirror: int = Query(0),
    ts: float = Query(0.5),
) -> Response:
    """ffmpeg-rendered preview of a staged file, with rotation/mirror applied."""
    path = _staged_path(stage_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="staged file not found")
    try:
        img = make_preview_image(path, rotation=rotation, mirror=bool(mirror), ts=ts)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return Response(content=img, media_type="image/jpeg")


@app.delete("/stage/{stage_id}", status_code=204, response_model=None)
def unstage(stage_id: str) -> None:
    """Drop a staged file (e.g. after a successful upload or a cancelled pick)."""
    path = _staged_path(stage_id)
    if path and path.exists():
        path.unlink(missing_ok=True)


@app.post("/videos", status_code=201)
async def upload_video(
    file: UploadFile = File(...),
    location: str = Form(...),
    name: str = Form(""),
    record_time: Optional[str] = Form(None),
    rotation: int = Form(0),
    mirror: int = Form(0),
    stage_id: Optional[str] = Form(None),
) -> dict[str, Any]:
    """Store a video + its metadata to disk, then transcode to MP4 in background.

    The raw file is saved immediately and a DB row inserted (status='uploaded').
    A background task transcodes to H.264+AAC (baking rotation/mirror into pixels).
    The frontend polls for status to track progress.
    """
    location = (location or "").strip()
    if not location:
        raise HTTPException(status_code=422, detail="location is required")
    suffix = _check_suffix(file.filename or "")

    video_id = uuid.uuid4().hex
    raw_suffix = suffix
    raw_filename = f"{video_id}_raw{raw_suffix}"

    # Save raw file directly to UPLOAD_DIR, then probe for initial metadata.
    raw_dest = UPLOAD_DIR / raw_filename
    _save_upload(file, raw_dest)
    try:
        props = probe_video(raw_dest)
    except RuntimeError as exc:
        raw_dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"probe failed: {exc}")

    record_time = (record_time or "").strip() or _now_iso()
    has_audio = bool(props.get("has_audio"))

    # Insert DB row — status='uploaded', storing the raw filename with
    # original rotation/mirror (preview applies them until transcode bakes them in).
    with closing(get_db()) as conn, conn:
        conn.execute(
            """INSERT INTO videos
               (id, stored_name, orig_name, name, location, record_time,
                upload_time, rotation, mirror, fps, has_audio, duration,
                width, height, container, size_bytes, status,
                transcription_status, transcription_progress,
                transcode_progress, transcode_error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                video_id,
                raw_filename,
                file.filename or f"{video_id}_raw{raw_suffix}",
                name.strip(),
                location,
                record_time,
                _now_iso(),
                rotation % 360,
                1 if mirror else 0,
                props["fps"],
                int(has_audio),
                props["duration"],
                props["width"],
                props["height"],
                props["container"],
                props["size_bytes"],
                "queued",
                "untranscribed",
                0.0,
                0.0,
                None,
            ),
        )

    # The staged copy (if any) is no longer needed.
    if stage_id:
        staged = _staged_path(stage_id)
        if staged:
            staged.unlink(missing_ok=True)

    return {
        "id": video_id,
        "status": "queued",
        "transcode_progress": 0.0,
        "rotation": rotation % 360,
        "mirror": bool(mirror),
        **props,
    }


@app.get("/videos")
def list_videos(
    sort_by: str = Query("upload_time", description="location|upload_time|name|record_time"),
    order: str = Query("desc", description="asc|desc"),
) -> list[dict[str, Any]]:
    """List all uploaded videos, sorted by the requested column."""
    if sort_by not in SORTABLE_COLUMNS:
        raise HTTPException(
            status_code=422,
            detail=f"sort_by must be one of {sorted(SORTABLE_COLUMNS)}",
        )
    order = order.lower()
    if order not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="order must be asc or desc")

    # sort_by/order are validated against whitelists above -> safe to interpolate.
    query = f"SELECT * FROM videos ORDER BY {sort_by} COLLATE NOCASE {order.upper()}"
    with closing(get_db()) as conn:
        rows = conn.execute(query).fetchall()
    return [_row_to_dict(r) for r in rows]


@app.get("/videos/{video_id}")
def get_video(video_id: str) -> dict[str, Any]:
    """Retrieve a single video's metadata + properties."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="video not found")
    return _row_to_dict(row)


@app.get("/videos/{video_id}/preview")
def video_preview(
    video_id: str,
    ts: float = Query(0.5),
    rotation: Optional[int] = Query(None),
    mirror: Optional[int] = Query(None),
) -> Response:
    """ffmpeg-rendered preview of a stored video.

    Uses the stored rotation/mirror metadata unless explicitly overridden via
    query params.
    """
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT stored_name, rotation, mirror FROM videos WHERE id = ?",
            (video_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="video not found")

    path = UPLOAD_DIR / row["stored_name"]
    if not path.exists():
        raise HTTPException(status_code=410, detail="file missing on disk")

    rot = row["rotation"] if rotation is None else rotation
    mir = bool(row["mirror"]) if mirror is None else bool(mirror)
    try:
        img = make_preview_image(path, rotation=rot, mirror=mir, ts=ts)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return Response(content=img, media_type="image/jpeg")


@app.get("/media/{video_id}")
def stream_video(video_id: str) -> FileResponse:
    """Serve the transcoded MP4 (H.264+AAC, transforms baked in)."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT stored_name FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="video not found")

    path = UPLOAD_DIR / row["stored_name"]
    if not path.exists():
        raise HTTPException(status_code=410, detail="file missing on disk")
    return FileResponse(path)


@app.get("/locations")
def list_locations() -> list[str]:
    """Distinct known locations, for the front-end autocomplete/datalist."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT DISTINCT location FROM videos ORDER BY location COLLATE NOCASE"
        ).fetchall()
    return [r["location"] for r in rows]


@app.delete("/videos/{video_id}", status_code=204, response_model=None)
async def delete_video(video_id: str) -> None:
    """Remove a video from disk and the catalogue (handy during trials).

    Cancels any in-flight transcode and transcription tasks for this video,
    and cleans up all associated disk files and temp directories.
    """
    # Cancel running transcode task / process first.
    task = _running_transcode_tasks.pop(video_id, None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    proc = _running_transcode_procs.pop(video_id, None)
    if proc is not None:
        try:
            proc.terminate()
            await proc.wait()
        except (ProcessLookupError, Exception):
            pass

    # Signal any running transcription job to abort gracefully.
    _cancelled_video_ids.add(video_id)
    transcribe_job_id = _running_transcribe_jobs.pop(video_id, None)
    if transcribe_job_id is not None:
        # Wait until the worker deregisters and removes video_id from the set.
        while video_id in _cancelled_video_ids:
            await asyncio.sleep(0.5)

    with closing(get_db()) as conn, conn:
        row = conn.execute(
            "SELECT stored_name FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        if row is None:
            # If the DB row is already gone, still clean up disk files.
            _cleanup_video_disk_files(video_id)
            raise HTTPException(status_code=404, detail="video not found")
        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))

    # Remove all disk artifacts for this video.
    _cleanup_video_disk_files(video_id, row["stored_name"])


def _cleanup_video_disk_files(video_id: str, stored_name: str | None = None) -> None:
    """Remove all disk files associated with a video (raw, mp4, chunk temp dirs)."""
    if stored_name is not None:
        (UPLOAD_DIR / stored_name).unlink(missing_ok=True)
    (UPLOAD_DIR / f"{video_id}.mp4").unlink(missing_ok=True)
    # Remove any leftover transcription chunk temp dirs for this video.
    for p in Path(tempfile.gettempdir()).iterdir():
        if p.is_dir() and p.name.startswith(f"transcribe_{video_id}_"):
            shutil.rmtree(p, ignore_errors=True)


@app.post("/videos/{video_id}/transcriptions/import", status_code=201)
async def import_transcriptions(
    video_id: str, payload: TranscriptionImportPayload = Body(...)
) -> dict[str, Any]:
    """Import frame/audio transcriptions for a video (replaces existing rows)."""
    with closing(get_db()) as conn, conn:
        video = conn.execute(
            "SELECT id FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        if video is None:
            raise HTTPException(status_code=404, detail="video not found")

        conn.execute("DELETE FROM frame_descriptions WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM audio_transcriptions WHERE video_id = ?", (video_id,))

        for f in payload.frame_descriptions:
            conn.execute(
                "INSERT INTO frame_descriptions (video_id, timestamp, description) VALUES (?,?,?)",
                (video_id, f.timestamp, f.description),
            )
        for a in payload.transcriptions:
            conn.execute(
                "INSERT INTO audio_transcriptions (video_id, segment_index, start_seconds, end_seconds, text) VALUES (?,?,?,?,?)",
                (video_id, a.index, a.start_seconds, a.end_seconds, a.text),
            )

    return {
        "video_id": video_id,
        "frames_imported": len(payload.frame_descriptions),
        "audio_imported": len(payload.transcriptions),
    }


@app.get("/videos/{video_id}/transcriptions")
def list_transcriptions(video_id: str) -> dict[str, Any]:
    """List imported frame descriptions and audio transcriptions for a video."""
    with closing(get_db()) as conn:
        video = conn.execute(
            "SELECT id FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        if video is None:
            raise HTTPException(status_code=404, detail="video not found")

        frames = conn.execute(
            "SELECT timestamp, description FROM frame_descriptions "
            "WHERE video_id = ? ORDER BY timestamp",
            (video_id,),
        ).fetchall()
        audio = conn.execute(
            "SELECT segment_index, start_seconds, end_seconds, text FROM audio_transcriptions "
            "WHERE video_id = ? ORDER BY start_seconds",
            (video_id,),
        ).fetchall()

    return {
        "frame_descriptions": [dict(r) for r in frames],
        "transcriptions": [dict(r) for r in audio],
    }


@app.get("/search")
def search_transcriptions(
    q: str = Query(..., min_length=1, max_length=200),
    source: Optional[str] = Query(None, pattern="^(frame|audio)$"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Mixed FTS5 + substring search across frame descriptions and audio text."""
    with closing(get_db()) as conn:
        results = _search_transcriptions(conn, q.strip(), source, limit)
    return {"results": results}


# --------------------------------------------------------------------------- #
# Search helpers — image-to-text / audio-to-text
# --------------------------------------------------------------------------- #

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".webm"}


@app.post("/search/helpers/image-to-text")
async def image_to_text(file: UploadFile = File(...)) -> dict[str, str]:
    """Upload an image, describe it with VLM, return the description as text."""
    suffix = Path(file.filename or "image.jpg").suffix.lower()
    if suffix not in _IMAGE_EXTENSIONS:
        raise HTTPException(status_code=415, detail="unsupported image format")

    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            tmp = Path(f.name)
            _save_upload(file, tmp)
        client = vlm_client()
        text = await asyncio.to_thread(client.describe, tmp)
        return {"text": text}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)


@app.post("/search/helpers/audio-to-text")
async def audio_to_text(file: UploadFile = File(...)) -> dict[str, str]:
    """Upload an audio clip, transcribe it with ASR, return the text."""
    suffix = Path(file.filename or "audio.wav").suffix.lower()
    if suffix not in _AUDIO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="unsupported audio format")

    work_dir: Path | None = None
    try:
        work_dir = Path(tempfile.mkdtemp())
        tmp_raw = work_dir / f"input{suffix}"
        _save_upload(file, tmp_raw)
        wav = convert_audio_to_wav(tmp_raw, work_dir)
        client = asr_client()
        segments = await asyncio.to_thread(client.transcribe, wav)
        full_text = " ".join(s["text"] for s in segments)
        return {"text": full_text}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if work_dir and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Agentic chat — tools
# --------------------------------------------------------------------------- #

_AGENT_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
    "is", "are", "was", "were", "be", "this", "that", "it", "with",
    "from", "by", "as", "not", "no", "so", "but", "if", "then",
    "有", "了", "的", "是", "在", "我", "你", "他", "她", "它", "这", "那",
    "和", "与", "就", "都", "也", "很", "一", "个", "不", "把", "被", "着",
}
_CJK_WORD_RE = re.compile(r"[一-鿿]{2,}|[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")


def _tokenize_text(text: str) -> list[str]:
    """Tokenize mixed Chinese/English text into keyword tokens.

    CJK runs of >=2 chars are kept whole (Chinese words usually span 2+ chars);
    ASCII words/numbers are lower-cased.
    """
    return _CJK_WORD_RE.findall((text or "").lower())


# --------------------------------------------------------------------------- #
# Agent search expression parser/evaluator
# --------------------------------------------------------------------------- #

class _ExprNode:
    """Tiny AST node for boolean search expressions."""

    __slots__ = ("kind", "value", "left", "right")

    def __init__(
        self,
        kind: str,
        value: str = "",
        left: "_ExprNode | None" = None,
        right: "_ExprNode | None" = None,
    ) -> None:
        self.kind = kind  # "LEAF" | "AND" | "OR"
        self.value = value
        self.left = left
        self.right = right


class _ExprToken:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str = "") -> None:
        self.kind = kind
        self.value = value


def _tokenize_search_expr(expr: str) -> list[_ExprToken]:
    """Tokenize a boolean query expression.

    Supports:
      - double-quoted phrases: "credit card"
      - parentheses: ( ... )
      - operators: AND, OR (case-insensitive)
      - bare words
    """
    tokens: list[_ExprToken] = []
    i = 0
    n = len(expr)
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c == "(":
            tokens.append(_ExprToken("LPAREN"))
            i += 1
            continue
        if c == ")":
            tokens.append(_ExprToken("RPAREN"))
            i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n and expr[j] != '"':
                j += 1
            tokens.append(_ExprToken("TERM", expr[i + 1 : j]))
            i = j + 1
            continue
        # bare word
        j = i
        while j < n and not expr[j].isspace() and expr[j] not in "()\"":
            j += 1
        word = expr[i:j]
        upper = word.upper()
        if upper == "AND":
            tokens.append(_ExprToken("AND"))
        elif upper == "OR":
            tokens.append(_ExprToken("OR"))
        else:
            tokens.append(_ExprToken("TERM", word))
        i = j
    return tokens


def _parse_search_expr(tokens: list[_ExprToken], pos: int = 0) -> tuple[_ExprNode, int]:
    """Parse tokens into an AST (precedence: AND before OR)."""
    left, pos = _parse_search_term(tokens, pos)
    while pos < len(tokens) and tokens[pos].kind == "AND":
        pos += 1
        right, pos = _parse_search_term(tokens, pos)
        left = _ExprNode("AND", left=left, right=right)
    while pos < len(tokens) and tokens[pos].kind == "OR":
        pos += 1
        right, pos = _parse_search_expr(tokens, pos)
        left = _ExprNode("OR", left=left, right=right)
    return left, pos


def _parse_search_term(tokens: list[_ExprToken], pos: int) -> tuple[_ExprNode, int]:
    if pos >= len(tokens):
        raise ValueError("unexpected end of expression")
    tok = tokens[pos]
    if tok.kind == "LPAREN":
        node, pos = _parse_search_expr(tokens, pos + 1)
        if pos >= len(tokens) or tokens[pos].kind != "RPAREN":
            raise ValueError("missing closing parenthesis")
        return node, pos + 1
    if tok.kind == "TERM":
        return _ExprNode("LEAF", value=tok.value), pos + 1
    raise ValueError(f"unexpected token {tok.kind} in expression")


_ExprHitKey = tuple[str, int]


def _eval_search_expr(
    node: _ExprNode,
    conn: sqlite3.Connection,
    source: Optional[str],
    per_term_limit: int,
) -> dict[_ExprHitKey, dict[str, Any]]:
    """Evaluate a boolean expression, returning a deduplicated hit map."""
    if node.kind == "LEAF":
        hits: dict[_ExprHitKey, dict[str, Any]] = {}
        term = node.value
        for hit in _search_transcriptions(conn, term, source, per_term_limit):
            key: _ExprHitKey = (hit["source"], hit["row_id"])
            hit["match_count"] = 1
            hit["matched_terms"] = [term]
            hits[key] = hit
        return hits

    left = _eval_search_expr(node.left, conn, source, per_term_limit)
    right = _eval_search_expr(node.right, conn, source, per_term_limit)

    if node.kind == "AND":
        result: dict[_ExprHitKey, dict[str, Any]] = {}
        for key, lh in left.items():
            rh = right.get(key)
            if rh is None:
                continue
            merged_terms = list(dict.fromkeys(lh.get("matched_terms", []) + rh.get("matched_terms", [])))
            lh["matched_terms"] = merged_terms
            lh["match_count"] = len(merged_terms)
            result[key] = lh
        return result

    # OR
    result = dict(left)
    for key, rh in right.items():
        lh = result.get(key)
        if lh is None:
            result[key] = rh
        else:
            merged_terms = list(dict.fromkeys(lh.get("matched_terms", []) + rh.get("matched_terms", [])))
            lh["matched_terms"] = merged_terms
            lh["match_count"] = len(merged_terms)
    return result


def _agent_search(
    q: str,
    source: Optional[str] = None,
    limit: int = 20,
    operand: str = "OR",
) -> list[dict[str, Any]]:
    """Agent tool: search transcriptions, returning compact hits with play_url.

    Splits *q* on whitespace and searches each token separately.  By default
    results are merged with OR semantics (a hit matching any token is
    returned), ranked so items matching more terms appear first.  Set
    *operand* to "AND" to require every token to match.  Set *operand* to
    "EXPR" to evaluate a boolean expression with parentheses, AND/OR, and
    quoted phrases, e.g. ``(mouse OR keyboard) AND (screen OR \"credit card\")``.
    *source* "both" searches frame descriptions and audio transcriptions
    together.
    """
    if source not in (None, "frame", "audio", "both", "all"):
        raise agentic.ToolError(
            f"source must be 'frame', 'audio', 'both' or 'all', got {source!r}"
        )
    if operand not in ("OR", "AND", "EXPR"):
        raise agentic.ToolError(
            f"operand must be 'OR', 'AND' or 'EXPR', got {operand!r}"
        )

    effective_source = None if source in (None, "both", "all") else source
    q = (q or "").strip()
    if not q:
        return []

    with closing(get_db()) as conn:
        if operand == "EXPR":
            try:
                tokens = _tokenize_search_expr(q)
                ast, pos = _parse_search_expr(tokens)
                if pos != len(tokens):
                    raise ValueError("unexpected tokens after expression")
            except Exception as exc:
                raise agentic.ToolError(f"invalid EXPR query: {exc}") from exc
            hits_map = _eval_search_expr(
                ast, conn, effective_source, max(min(int(limit) * 2, 50), 20)
            )
            hits = sorted(
                hits_map.values(),
                key=lambda h: (
                    -h.get("match_count", 1),
                    h["rank"],
                    h["video"]["upload_time"] or "",
                ),
            )[: min(int(limit), 50)]
        elif operand == "AND":
            hits = _search_transcriptions(
                conn, q, effective_source, min(int(limit), 50)
            )
            tokens = [t for t in q.split() if t]
            for h in hits:
                h["match_count"] = len(tokens)
                h["matched_terms"] = tokens
        else:
            # OR: search per token and merge.
            tokens = [t for t in q.split() if t]
            merged: dict[_ExprHitKey, dict[str, Any]] = {}
            per_token_limit = max(min(int(limit) * 2, 50), 20)
            for token in tokens:
                for hit in _search_transcriptions(
                    conn, token, effective_source, per_token_limit
                ):
                    key: _ExprHitKey = (hit["source"], hit["row_id"])
                    existing = merged.get(key)
                    if existing is None:
                        hit["match_count"] = 1
                        hit["matched_terms"] = [token]
                        merged[key] = hit
                    else:
                        existing["match_count"] = existing.get("match_count", 1) + 1
                        if token not in existing["matched_terms"]:
                            existing["matched_terms"].append(token)
            hits = sorted(
                merged.values(),
                key=lambda h: (
                    -h.get("match_count", 1),
                    h["rank"],
                    h["video"]["upload_time"] or "",
                ),
            )[: min(int(limit), 50)]

    out: list[dict[str, Any]] = []
    for h in hits:
        v = h["video"]
        out.append({
            "video_id": v["id"],
            "video_name": v.get("name") or v.get("location") or "untitled",
            "location": v.get("location") or "",
            "source": h["source"],
            "timestamp": h["timestamp"],
            "end_timestamp": h.get("end_timestamp"),
            "context_start": h["context_start"],
            "context_end": h["context_end"],
            "text": h["text"],
            "excerpt": h["excerpt"],
            "play_url": f"/media/{v['id']}#t={h['timestamp']}",
            "match_count": h.get("match_count", 1),
            "matched_terms": h.get("matched_terms", []),
        })
    return out


def _agent_list_videos() -> list[dict[str, Any]]:
    """Agent tool: list videos with identity + processing status."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, name, location, record_time, upload_time, duration,"
            " status, transcription_status FROM videos ORDER BY upload_time DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def _agent_video_keywords(video_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Agent tool: top keyword terms across a video's transcriptions (by freq)."""
    with closing(get_db()) as conn:
        if conn.execute("SELECT id FROM videos WHERE id = ?", (video_id,)).fetchone() is None:
            raise agentic.ToolError(f"video not found: {video_id}")
        frames = conn.execute(
            "SELECT description FROM frame_descriptions WHERE video_id = ?",
            (video_id,),
        ).fetchall()
        audio = conn.execute(
            "SELECT text FROM audio_transcriptions WHERE video_id = ?",
            (video_id,),
        ).fetchall()
    text = " ".join(r["description"] for r in frames) + " " + " ".join(r["text"] for r in audio)
    counts = Counter(
        t for t in _tokenize_text(text)
        if t not in _AGENT_STOPWORDS and len(t) > 1
    )
    return [{"term": term, "count": cnt} for term, cnt in counts.most_common(int(limit))]


_AGENT_WINDOW_MAX = 30  # max seconds of transcription the agent may view per call


def _agent_video_transcriptions(
    video_id: str,
    start_sec: float = 0.0,
    window_sec: int = 30,
) -> dict[str, Any]:
    """Agent tool: read ONE window (max 30s) of a video's transcriptions.

    The agent can never see the whole video at once — only ``window_sec``
    seconds starting at ``start_sec`` (default 0–30s).  The agent must specify
    the starting second; the window is clamped to at most 30s.  Video metadata
    (incl. ``duration``) is returned so the agent knows how many windows to
    scan — it calls again with later ``start_sec`` values to cover more.
    Frames whose timestamp falls inside the window and audio segments that
    overlap it are returned.
    """
    start_sec = max(0.0, float(start_sec))
    window_sec = max(1, min(_AGENT_WINDOW_MAX, int(window_sec)))
    end_sec = start_sec + window_sec

    with closing(get_db()) as conn:
        meta = conn.execute(
            "SELECT id, name, location, record_time, duration, status,"
            " transcription_status FROM videos WHERE id = ?",
            (video_id,),
        ).fetchone()
        if meta is None:
            raise agentic.ToolError(f"video not found: {video_id}")
        frames = conn.execute(
            "SELECT timestamp, description FROM frame_descriptions"
            " WHERE video_id = ? AND timestamp >= ? AND timestamp < ?"
            " ORDER BY timestamp",
            (video_id, start_sec, end_sec),
        ).fetchall()
        audio = conn.execute(
            "SELECT segment_index, start_seconds, end_seconds, text FROM audio_transcriptions"
            " WHERE video_id = ? AND start_seconds < ? AND end_seconds >= ?"
            " ORDER BY start_seconds",
            (video_id, end_sec, start_sec),
        ).fetchall()

    return {
        "video_id": video_id,
        "metadata": dict(meta),
        "window": {
            "start_sec": start_sec,
            "end_sec": end_sec,
            "window_sec": window_sec,
            "note": f"you can view at most {_AGENT_WINDOW_MAX}s of transcription at a time; "
                    "to see more, call again with a later start_sec (e.g. 30, 60, …) up to "
                    "metadata.duration",
        },
        "frame_descriptions": [dict(r) for r in frames],
        "transcriptions": [dict(r) for r in audio],
    }


def _agent_media_url(video_id: str, timestamp: float = 0.0) -> dict[str, Any]:
    """Agent tool: build a play_url that jumps to a timestamp in a video."""
    with closing(get_db()) as conn:
        if conn.execute("SELECT id FROM videos WHERE id = ?", (video_id,)).fetchone() is None:
            raise agentic.ToolError(f"video not found: {video_id}")
    ts = float(timestamp)
    return {"video_id": video_id, "timestamp": ts, "play_url": f"/media/{video_id}#t={ts}"}


_FEATURE_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "on", "in", "at", "to", "with",
    "is", "are", "was", "were", "for", "it", "its", "this", "that",
}


def _feature_subqueries(feat: str) -> list[str]:
    """Split a feature descriptor into searchable sub-queries.

    The full phrase is searched first; individual words are added so a
    descriptor like "above the display" still matches "above" or "display"
    even when the exact phrase is not contiguous in a transcription.
    """
    parts = [p for p in re.split(r"\s+", feat.strip()) if p]
    if not parts:
        return []
    subs = [feat.strip()]
    for p in parts:
        if len(p) >= 3 and p.lower() not in _FEATURE_STOPWORDS:
            subs.append(p)
    return subs


def _extract_json_block(text: str) -> Optional[dict[str, Any]]:
    """Pull the first JSON object out of a model response (with fence tolerant)."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- #
# Stateless single-tool subagents for suggest_likely_moments
# --------------------------------------------------------------------------- #

_SUBAGENT_SYSTEM_PROMPT = """\
You are an autonomous research subagent. You have NO memory and NO conversation history.
You will receive ONE objective. You may call EXACTLY ONE tool to investigate it.
After you see the tool result, reply with a concise 1-3 sentence summary for the master agent.
Use Chinese and English search terms when they may help. Do NOT call suggest_likely_moments.
"""


def _subagent_tool_schemas() -> list[dict[str, Any]]:
    """Schemas available to a single-tool subagent (all except suggest_likely_moments)."""
    return [
        s for s in _agent_schemas(incognito=False)
        if s.get("function", {}).get("name") != "suggest_likely_moments"
    ]


def _subagent_tool_impls() -> dict[str, Any]:
    """Tool implementations available to a single-tool subagent."""
    memory = agentic.AgentMemory(DB_PATH)
    feedback = agentic.AgentFeedback(DB_PATH)
    impls = _build_agent_tool_impls(memory, feedback, session_id="", incognito=False)
    impls.pop("suggest_likely_moments", None)
    return impls


def _run_single_tool_subagent(objective: str) -> dict[str, Any]:
    """Run one stateless subagent: decide one tool, execute it, return summary."""
    cfg = get_agent_config()
    llm = agent_llm_client(cfg)
    schemas = _subagent_tool_schemas()
    impls = _subagent_tool_impls()

    messages = [
        {"role": "system", "content": _SUBAGENT_SYSTEM_PROMPT},
        {"role": "user", "content": objective},
    ]

    try:
        resp = llm.chat(messages, schemas)
    except Exception as exc:
        return {"summary": f"Subagent failed to choose a tool: {exc}"}

    if resp.kind != "tool_call":
        return {"summary": resp.content or "Subagent did not make a tool call."}

    tool_name = resp.tool
    arguments = resp.arguments
    if tool_name not in impls:
        return {
            "tool": tool_name,
            "arguments": arguments,
            "summary": f"Subagent tried unavailable tool {tool_name!r}.",
        }

    try:
        result = impls[tool_name](**arguments)
    except Exception as exc:
        return {
            "tool": tool_name,
            "arguments": arguments,
            "summary": f"Tool {tool_name!r} failed: {exc}",
        }

    # Second (and final) turn: ask the subagent to summarize the tool result.
    messages.append({
        "role": "assistant",
        "content": json.dumps(resp.to_dict(), ensure_ascii=False),
    })
    messages.append({
        "role": "user",
        "content": (
            "Summarize the tool result concisely in 1-3 sentences for the master agent. "
            "If you found promising moments, mention their timestamps and why they are relevant.\n\n"
            + json.dumps(result, ensure_ascii=False, default=str)[:2000]
        ),
    })
    try:
        summary_resp = llm.chat(messages, [])
        summary = summary_resp.content or ""
    except Exception as exc:
        summary = f"Tool succeeded but subagent summary failed: {exc}"

    return {
        "tool": tool_name,
        "arguments": arguments,
        "result": result,
        "summary": summary.strip(),
    }


def _agent_suggest_likely_moments(
    target: str,
    features: list[str],
    video_id: str = "",
    limit: int = 10,
    subagent_calls: int = 3,
) -> dict[str, Any]:
    """Agent tool: phenomenological fallback search by features, not names.

    Vision-model captions rarely name an object (a webcam is "a dark glossy
    protruding circle at the top edge").  This tool spawns 1-5 stateless
    single-tool subagents (default 3).  Each subagent has no history, receives
    only the objective, calls exactly one tool, and returns a concise summary.
    Results from all subagents are aggregated into ranked "likely" candidates
    with an explicit uncertainty note so the agent never has to refuse.  If
    every subagent fails, the tool falls back to literal feature search.
    """
    target = (target or "").strip()
    feats = [str(f).strip() for f in (features or []) if str(f).strip()]
    if not feats:
        raise agentic.ToolError(
            "suggest_likely_moments requires at least one feature descriptor"
        )

    subagent_calls = max(1, min(5, int(subagent_calls or 3)))

    objective = (
        f"Target object: {target}\n"
        f"Visual/spatial features: {', '.join(feats)}\n"
        + (f"Focus only on video_id: {video_id}\n" if video_id else "Search across all videos.\n")
        + "Call exactly ONE tool to find promising moments. Prefer search_transcriptions. "
          "Use both Chinese and English terms/synonyms. Then summarize what you found."
    )

    subagent_results: list[dict[str, Any]] = []
    for i in range(subagent_calls):
        try:
            res = _run_single_tool_subagent(objective)
            subagent_results.append(res)
            log.debug(
                "[suggest] subagent %d/%d summary: %s",
                i + 1,
                subagent_calls,
                res.get("summary", "")[:120],
            )
        except Exception as exc:
            log.warning("[suggest] subagent %d/%d failed: %s", i + 1, subagent_calls, exc)
            subagent_results.append({"summary": f"Subagent failed: {exc}"})

    # Aggregate search hits discovered by the subagents.
    by_key: dict[tuple[str, str, float], dict[str, Any]] = {}
    for res in subagent_results:
        if res.get("tool") != "search_transcriptions":
            continue
        arguments = res.get("arguments", {})
        query_text = (arguments.get("q") or "").strip()
        for hit in res.get("result", []):
            if video_id and hit.get("video_id") != video_id:
                continue
            key = (
                hit.get("video_id"),
                hit.get("source"),
                round(float(hit.get("timestamp", 0)), 3),
            )
            entry = by_key.setdefault(key, {
                "video_id": hit.get("video_id"),
                "video_name": hit.get("video_name") or "untitled",
                "location": hit.get("location") or "",
                "source": hit.get("source"),
                "timestamp": float(hit.get("timestamp", 0)),
                "end_timestamp": hit.get("end_timestamp"),
                "text": hit.get("text", ""),
                "matched_features": [],
                "subagent_summaries": [],
                "search_queries": [],
            })
            if query_text and query_text not in entry["search_queries"]:
                entry["search_queries"].append(query_text)
            summary = res.get("summary", "")
            if summary and summary not in entry["subagent_summaries"]:
                entry["subagent_summaries"].append(summary)
            # Attribute the hit to original features by text/query overlap.
            hit_text = (hit.get("text", "") or "").lower()
            for feat in feats:
                if feat.lower() in hit_text:
                    if feat not in entry["matched_features"]:
                        entry["matched_features"].append(feat)
                    continue
                for subq in _feature_subqueries(feat):
                    if subq.lower() in query_text.lower():
                        if feat not in entry["matched_features"]:
                            entry["matched_features"].append(feat)
                        break

    # Fallback: if subagents produced no candidates, fall back to literal search.
    if not by_key:
        log.warning("[suggest] subagents found no candidates; falling back to literal search")
        for feat in feats:
            for subq in _feature_subqueries(feat):
                if len(subq) < 2:
                    continue
                with closing(get_db()) as conn:
                    hits = _search_transcriptions(conn, subq, None, 100)
                for h in hits:
                    v = h["video"]
                    if video_id and v["id"] != video_id:
                        continue
                    key = (v["id"], h["source"], round(h["timestamp"], 3))
                    entry = by_key.setdefault(key, {
                        "video_id": v["id"],
                        "video_name": v.get("name") or v.get("location") or "untitled",
                        "location": v.get("location") or "",
                        "source": h["source"],
                        "timestamp": h["timestamp"],
                        "end_timestamp": h.get("end_timestamp"),
                        "text": h["text"],
                        "matched_features": [],
                        "subagent_summaries": [],
                        "search_queries": [],
                    })
                    if feat not in entry["matched_features"]:
                        entry["matched_features"].append(feat)

    candidates = sorted(
        by_key.values(),
        key=lambda c: (-len(c["matched_features"]), -len(c["search_queries"]), c["timestamp"]),
    )
    for c in candidates:
        n = len(c["matched_features"])
        c["feature_count"] = n
        c["play_url"] = f"/media/{c['video_id']}#t={c['timestamp']}"
        c["note"] = (
            f"likely candidate — matches {n} typical {target or 'object'} feature(s)"
        )

    return {
        "target": target,
        "features_searched": feats,
        "candidates": candidates[: int(limit)],
        "subagent_summaries": [
            r.get("summary", "") for r in subagent_results if r.get("summary")
        ],
        "uncertainty": (
            f"No confirmed match for {target!r}. These are the most likely moments "
            "based on typical appearance/placement features — NOT confirmed "
            "matches. Verify visually before relying on them."
        ),
    }


def _agent_get_feedback_history(
    query: str = "",
    video_id: str = "",
    source: str = "",
    rating: Optional[int] = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Agent tool: review past thumbs up/down feedback (global across sessions).

    Used by the agent to learn which query terms / items were confirmed or
    rejected by the user, and to improve future searches.
    """
    entries = agentic.AgentFeedback(DB_PATH).list(
        query=query, video_id=video_id, source=source,
        rating=rating, limit=min(int(limit), 200),
    )
    return {"feedback": entries}


# Tools that expose private state (memory / feedback). Disabled in incognito
# mode so the agent only has pure read-only access to transcriptions.
_PRIVATE_TOOL_NAMES = frozenset({
    "memory_store", "memory_get", "memory_list", "memory_delete",
    "memory_delete_where", "get_feedback_history",
    "feedback_set", "feedback_delete",
})


def _agent_schemas(incognito: bool = False) -> list[dict[str, Any]]:
    if not incognito:
        return _AGENT_TOOL_SCHEMAS
    return [
        s for s in _AGENT_TOOL_SCHEMAS
        if s.get("function", {}).get("name") not in _PRIVATE_TOOL_NAMES
    ]


def _build_agent_tool_impls(
    memory: agentic.AgentMemory,
    feedback: agentic.AgentFeedback,
    session_id: str = "",
    incognito: bool = False,
) -> dict[str, Any]:
    """Assemble the tool callables; memory/feedback tools close over the stores.

    In incognito mode only the pure read-only transcription tools are exposed
    (no memory, no feedback).
    """
    read_tools: dict[str, Any] = {
        "search_transcriptions": _agent_search,
        "list_videos": _agent_list_videos,
        "get_video_keywords": _agent_video_keywords,
        "get_video_transcriptions": _agent_video_transcriptions,
        "get_media_url": _agent_media_url,
        "suggest_likely_moments": _agent_suggest_likely_moments,
    }
    if incognito:
        return read_tools

    main_session_id = session_id

    def _feedback_set(video_id, source, timestamp, rating,
                      end_timestamp=None, user_message="", agent_reply="", **kw):
        """Agent tool: create/edit a rating on an item (current session)."""
        if rating not in (1, -1):
            raise agentic.ToolError("rating must be 1 (up) or -1 (down)")
        if not session_id:
            raise agentic.ToolError("feedback_set requires an active session")
        return feedback.upsert(
            session_id=session_id, video_id=video_id, source=source,
            timestamp=timestamp, end_timestamp=end_timestamp, rating=rating,
            user_message=user_message, agent_reply=agent_reply,
        )

    def _feedback_delete(query="", video_id="", source="", session_id=""):
        """Agent tool: bulk-delete feedback matching filters.

        When the user asks to discard feedback "related to X", the agent passes
        a query/video_id and the delete spans all chats. ``session_id`` is only
        defaulted to the current conversation when no other filter is given.
        """
        if not (query or video_id or source or session_id):
            session_id = main_session_id
        try:
            deleted = feedback.delete_many(
                query=query, video_id=video_id, source=source,
                session_id=session_id,
            )
        except ValueError as exc:
            raise agentic.ToolError(str(exc)) from exc
        return {"deleted": deleted}

    def _memory_delete_where(contains):
        return {"deleted": memory.delete_where(contains)}

    read_tools.update({
        "get_feedback_history": _agent_get_feedback_history,
        "feedback_set": _feedback_set,
        "feedback_delete": _feedback_delete,
        "memory_store": memory.store,
        "memory_get": lambda key: (
            {"key": key, "value": (memory.get(key) or {})["value"]}
            if memory.get(key) else {"key": key, "not_found": True}
        ),
        "memory_list": lambda: {"entries": memory.list()},
        "memory_delete": lambda key: {"key": key, "deleted": memory.delete(key)},
        "memory_delete_where": _memory_delete_where,
    })
    return read_tools


_AGENT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "search_transcriptions",
        "description": "Full-text + substring search across frame descriptions and audio transcriptions. The query is split on whitespace and each token is searched separately. By default results are merged with OR semantics (any token matches), ranked so items matching more terms appear first. Set operand=AND to require every token to match. Set operand=EXPR to evaluate a boolean expression with parentheses, AND/OR operators, and quoted phrases, e.g. (mouse OR keyboard) AND (screen OR display OR \"credit card\"). Set source=both or source=all to search both frame and audio sources together.",
        "parameters": {"type": "object", "properties": {
            "q": {"type": "string", "description": "query terms (may mix languages); split on whitespace and searched per token, or parsed as a boolean expression when operand=EXPR"},
            "source": {"type": "string", "enum": ["frame", "audio", "both", "all"], "description": "restrict to frame, audio, or both/all (default: both/all searches frame + audio)"},
            "limit": {"type": "integer", "description": "max results (default 20)"},
            "operand": {"type": "string", "enum": ["OR", "AND", "EXPR"], "description": "OR = match any token (default), AND = require all tokens, EXPR = evaluate boolean expression with parentheses/AND/OR/quoted phrases"},
        }, "required": ["q"]},
    }},
    {"type": "function", "function": {
        "name": "list_videos",
        "description": "List all uploaded videos with id, name, location, duration and processing status.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "get_video_keywords",
        "description": "Top keyword terms for a video's transcriptions by frequency. Use this to discover query terms for a video.",
        "parameters": {"type": "object", "properties": {
            "video_id": {"type": "string"},
            "limit": {"type": "integer"},
        }, "required": ["video_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_video_transcriptions",
        "description": "Read frame descriptions + audio segments for ONE 30-second window of a video — never the whole video at once. You MUST specify the starting second (start_sec); the default window is 0–30s. The result includes video metadata (duration) so you know how many windows exist; to cover more of the video, call again with later start_sec values (0, 30, 60, …) up to metadata.duration.",
        "parameters": {"type": "object", "properties": {
            "video_id": {"type": "string"},
            "start_sec": {"type": "number", "description": "starting second of the 30s window you want (0 = beginning of video). Required — pick a window."},
            "window_sec": {"type": "integer", "description": "window length in seconds; max 30, default 30", "maximum": 30, "minimum": 1},
        }, "required": ["video_id", "start_sec"]},
    }},
    {"type": "function", "function": {
        "name": "get_media_url",
        "description": "Build a play_url that jumps to a timestamp within a video.",
        "parameters": {"type": "object", "properties": {
            "video_id": {"type": "string"},
            "timestamp": {"type": "number"},
        }, "required": ["video_id"]},
    }},
    {"type": "function", "function": {
        "name": "suggest_likely_moments",
        "description": "PHENOMENOLOGICAL fallback: when a direct name search for an object finds nothing, search by typical visual/spatial features (shape, color, position — e.g. lens, mounted, above the display, circular, small, dark, cables). This tool spawns 1-5 stateless single-tool subagents (default 3) with no conversation history; each subagent calls exactly one tool and returns a concise summary. Results are aggregated into ranked likely candidates. Use this instead of refusing, then express uncertainty in your answer.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "the object the user is looking for (e.g. 'webcam')"},
            "features": {"type": "array", "items": {"type": "string"}, "description": "typical visual/spatial feature descriptors of the object"},
            "video_id": {"type": "string", "description": "restrict to one video (optional)"},
            "limit": {"type": "integer", "description": "max candidates (default 10)"},
            "subagent_calls": {"type": "integer", "minimum": 1, "maximum": 5, "description": "number of stateless subagents to spawn (default 3)"},
        }, "required": ["target", "features"]},
    }},
    {"type": "function", "function": {
        "name": "get_feedback_history",
        "description": "Review past thumbs up/down feedback on retrieved items (across all chats), stored with the user question, your answer, and the query terms used. Learn from confirmed/rejected items to refine search terms.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "filter by text in the question/answer/query terms"},
            "video_id": {"type": "string"},
            "source": {"type": "string", "enum": ["frame", "audio"]},
            "rating": {"type": "integer", "description": "1 = thumbs up, -1 = thumbs down"},
            "limit": {"type": "integer"},
        }},
    }},
    {"type": "function", "function": {
        "name": "memory_store",
        "description": "Remember a term mapping (e.g. a correct term vs an ambiguous description the model mis-heard) for future conversations.",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
        }, "required": ["key", "value"]},
    }},
    {"type": "function", "function": {
        "name": "memory_get",
        "description": "Retrieve a previously stored memory entry by key.",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
    }},
    {"type": "function", "function": {
        "name": "memory_list",
        "description": "List all stored memory entries.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "memory_delete",
        "description": "Delete a stored memory entry by key.",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
    }},
    {"type": "function", "function": {
        "name": "memory_delete_where",
        "description": "Delete every memory entry whose key or value contains the given text. Use when the user asks to discard memory related to something (e.g. 'discard every memory related to ipod').",
        "parameters": {"type": "object", "properties": {
            "contains": {"type": "string"},
        }, "required": ["contains"]},
    }},
    {"type": "function", "function": {
        "name": "feedback_set",
        "description": "Create or edit a thumbs-up (+1) / thumbs-down (-1) rating on a retrieved item for the current conversation. Use when the user asks to record or change feedback on a specific item.",
        "parameters": {"type": "object", "properties": {
            "video_id": {"type": "string"},
            "source": {"type": "string", "enum": ["frame", "audio"]},
            "timestamp": {"type": "number"},
            "end_timestamp": {"type": "number"},
            "rating": {"type": "integer", "description": "1 = thumbs up, -1 = thumbs down"},
        }, "required": ["video_id", "source", "timestamp", "rating"]},
    }},
    {"type": "function", "function": {
        "name": "feedback_delete",
        "description": "Delete feedback matching the given filters. Use when the user asks to discard feedback (e.g. 'discard every feedback related to ipod'). Provide a query text, video_id, source, or session_id.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "delete feedback whose question/answer/query terms contain this text"},
            "video_id": {"type": "string"},
            "source": {"type": "string", "enum": ["frame", "audio"]},
            "session_id": {"type": "string"},
        }},
    }},
]


def _build_agent_runtime(
    session_id: str = "",
    incognito: bool = False,
) -> agentic.AgentRuntime:
    store = agentic.AgentSessionStore(DB_PATH)
    memory = agentic.AgentMemory(DB_PATH)
    feedback = agentic.AgentFeedback(DB_PATH)
    cfg = get_agent_config()
    return agentic.AgentRuntime(
        llm_client=agent_llm_client(cfg),
        tool_schemas=_agent_schemas(incognito=incognito),
        tool_impls=_build_agent_tool_impls(
            memory, feedback, session_id=session_id, incognito=incognito
        ),
        store=store,
        memory=memory,
        max_turns=cfg.max_turns,
        system_prompt=(
            agentic.SYSTEM_PROMPT_INCOGNITO if incognito else agentic.SYSTEM_PROMPT
        ),
    )


# --------------------------------------------------------------------------- #
# Agentic chat — API
# --------------------------------------------------------------------------- #

class AgentSessionCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field("", max_length=200)
    incognito: bool = False  # no memory/feedback — pure read-only transcriptions


class AgentAttachment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: Literal["image", "audio"]
    text: str = Field(..., min_length=1, max_length=8000)
    name: str = Field("", max_length=255)


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str = Field(..., min_length=1, max_length=4000)
    attachments: list[AgentAttachment] = Field(default_factory=list)
    incognito: bool = False  # run this single turn with no memory/feedback


class AgentMemoryUpsert(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key: str = Field(..., min_length=1, max_length=200)
    value: str = Field(..., min_length=1, max_length=4000)


class AgentFeedbackUpsert(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session_id: str = Field(..., min_length=1, max_length=64)
    video_id: str = Field(..., min_length=1, max_length=64)
    source: Literal["frame", "audio"]
    timestamp: float = Field(..., ge=0)
    end_timestamp: Optional[float] = Field(None, ge=0)
    rating: int = Field(..., ge=-1, le=1)
    user_message: str = Field("", max_length=4000)
    agent_reply: str = Field("", max_length=4000)


def _derive_feedback_context(session_id: str) -> tuple[str, str, str]:
    """Snapshot the chat context for feedback: last user question, last agent
    answer, and the most recent search query terms used in this session."""
    user_msg = ""
    agent_reply = ""
    tool_args = ""
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT role, content, tool_call_json FROM agent_messages"
            " WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
    for row in rows:
        if row["role"] == "user":
            user_msg = row["content"]
        elif row["role"] == "assistant":
            if row["tool_call_json"]:
                try:
                    meta = json.loads(row["tool_call_json"])
                    if meta.get("tool") == "search_transcriptions" and "arguments" in meta:
                        tool_args = json.dumps(meta["arguments"], ensure_ascii=False)
                except (json.JSONDecodeError, TypeError):
                    pass
            else:
                agent_reply = row["content"]
    return user_msg, agent_reply, tool_args


@app.post("/agent/sessions", status_code=201)
def create_agent_session(payload: AgentSessionCreate) -> dict[str, Any]:
    """Create a new agentic chat session.

    Set ``incognito: true`` for a chat that has NO memory or feedback (the
    agent only gets read-only access to the video transcriptions).
    """
    return agentic.AgentSessionStore(DB_PATH).create(payload.title, incognito=payload.incognito)


@app.get("/agent/sessions")
def list_agent_sessions() -> list[dict[str, Any]]:
    """List agentic chat sessions, most recently active first."""
    return agentic.AgentSessionStore(DB_PATH).list()


@app.get("/agent/sessions/{session_id}")
def get_agent_session(session_id: str) -> dict[str, Any]:
    """Return a session plus its full message history."""
    store = agentic.AgentSessionStore(DB_PATH)
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    return {"session": session, "messages": store.get_messages(session_id)}


@app.delete("/agent/sessions/{session_id}", status_code=204, response_model=None)
def delete_agent_session(session_id: str) -> None:
    """Delete a session (messages cascade)."""
    if not agentic.AgentSessionStore(DB_PATH).delete(session_id):
        raise HTTPException(status_code=404, detail="agent session not found")


@app.post("/agent/sessions/{session_id}/chat")
def agent_chat(session_id: str, payload: AgentChatRequest) -> dict[str, Any]:
    """Run one agentic turn for a user message.

    Runs the agent loop to a final answer (max AGENT_LLM_MAX_TURNS iterations).
    ``attachments`` are already-transcribed image/audio segments folded into the
    user context (see agentic.Attachment). An ``incognito`` session (or a turn
    sent with ``incognito: true``) has no memory/feedback — the agent only gets
    read-only access to the transcriptions.
    """
    _validate_agent_session(session_id)
    return {"session_id": session_id, **_run_agent_turn(session_id, payload)}


def _validate_agent_session(session_id: str) -> dict[str, Any]:
    session = agentic.AgentSessionStore(DB_PATH).get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    return session


def _run_agent_turn(session_id: str, payload: AgentChatRequest) -> dict[str, Any]:
    """Build the runtime for *payload* and run one agentic turn (synchronous)."""
    session = _validate_agent_session(session_id)
    incognito = bool(session.get("incognito")) or bool(payload.incognito)
    runtime = _build_agent_runtime(session_id=session_id, incognito=incognito)
    attachments = [
        agentic.Attachment(a.kind, a.text, a.name) for a in payload.attachments
    ]
    try:
        return runtime.run(session_id, payload.message, attachments=attachments)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/agent/sessions/{session_id}/chat/stream")
def agent_chat_stream(session_id: str, payload: AgentChatRequest) -> StreamingResponse:
    """Run one agentic turn and stream the reply as Server-Sent Events.

    Emits:
      * ``event: tool``   data: {tool, arguments}   — when the agent calls a tool
      * ``event: token``  data: {delta}             — live reply tokens (markdown)
      * ``event: done``   data: {reply, kind, ...}  — final result
      * ``event: error``  data: {error}             — on failure

    The agent loop runs in a background thread; the frontend renders the reply
    markdown live as tokens arrive, then re-renders from server truth on done.
    """
    _validate_agent_session(session_id)
    session = agentic.AgentSessionStore(DB_PATH).get(session_id)
    incognito = bool(session.get("incognito")) or bool(payload.incognito)
    runtime = _build_agent_runtime(session_id=session_id, incognito=incognito)
    attachments = [
        agentic.Attachment(a.kind, a.text, a.name) for a in payload.attachments
    ]

    import queue as _queue
    import threading as _threading

    q: "_queue.Queue[dict]" = _queue.Queue()

    def _on_token(delta: str) -> None:
        q.put({"type": "token", "delta": delta})

    def _on_tool(tool: str, arguments: dict) -> None:
        q.put({"type": "tool", "tool": tool, "arguments": arguments})

    def _run_worker() -> None:
        try:
            result = runtime.run(
                session_id, payload.message,
                attachments=attachments,
                on_token=_on_token,
                on_tool=_on_tool,
            )
            q.put({"type": "done", "result": {"session_id": session_id, **result}})
        except Exception as exc:  # noqa: BLE001 — surfaced to the client
            agentic.log.warning("[agent] stream worker error: %s", exc, exc_info=True)
            q.put({"type": "error", "error": str(exc)})

    _threading.Thread(target=_run_worker, daemon=True).start()

    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    def _generator():
        while True:
            item = q.get()
            if item["type"] == "token":
                yield f"event: token\n{_sse({'delta': item['delta']})}"
            elif item["type"] == "tool":
                yield f"event: tool\n{_sse({'tool': item['tool'], 'arguments': item['arguments']})}"
            elif item["type"] == "done":
                yield f"event: done\n{_sse(item['result'])}"
                break
            elif item["type"] == "error":
                yield f"event: error\n{_sse({'error': item['error']})}"
                break

    return StreamingResponse(_generator(), media_type="text/event-stream")


@app.get("/agent/memory")
def list_agent_memory() -> dict[str, Any]:
    """List the agent's persistent retrieval-enhancement memory."""
    return {"entries": agentic.AgentMemory(DB_PATH).list()}


@app.post("/agent/memory", status_code=201)
def upsert_agent_memory(payload: AgentMemoryUpsert) -> dict[str, Any]:
    """Store/update a retrieval-enhancement memory entry."""
    return agentic.AgentMemory(DB_PATH).store(payload.key, payload.value)


@app.delete("/agent/memory/{key}", status_code=204, response_model=None)
def delete_agent_memory(key: str) -> None:
    """Delete a retrieval-enhancement memory entry."""
    if not agentic.AgentMemory(DB_PATH).delete(key):
        raise HTTPException(status_code=404, detail="memory key not found")


@app.post("/agent/feedback", status_code=201)
def upsert_agent_feedback(payload: AgentFeedbackUpsert) -> dict[str, Any]:
    """Record thumbs up (+1) / down (-1) feedback on a retrieved item.

    The item is anchored by (session_id, video_id, source, timestamp). The user
    question + agent answer are snapshotted as context for the agent to learn
    from (unless supplied explicitly by the client).
    """
    session = agentic.AgentSessionStore(DB_PATH).get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    if session.get("incognito"):
        raise HTTPException(
            status_code=409,
            detail="incognito session: feedback is disabled (read-only)",
        )

    if payload.rating == 0:
        # rating 0 means "un-rate" — delete the entry.
        if not agentic.AgentFeedback(DB_PATH).delete(
            payload.session_id, payload.video_id, payload.source, payload.timestamp
        ):
            raise HTTPException(status_code=404, detail="feedback not found")
        return {"deleted": True}

    user_msg = payload.user_message
    agent_reply = payload.agent_reply
    # Context (question/answer/query-terms) is always backfilled from the
    # session history so ratings carry the exchange they belong to. The search
    # terms the agent used are derived server-side (ground truth), not trusted
    # from the client.
    d_user, d_reply, d_args = _derive_feedback_context(payload.session_id)
    user_msg = user_msg or d_user
    agent_reply = agent_reply or d_reply
    tool_args = d_args

    return agentic.AgentFeedback(DB_PATH).upsert(
        session_id=payload.session_id,
        video_id=payload.video_id,
        source=payload.source,
        timestamp=payload.timestamp,
        end_timestamp=payload.end_timestamp,
        rating=payload.rating,
        user_message=user_msg,
        agent_reply=agent_reply,
        tool_arguments=tool_args,
    )


@app.get("/agent/feedback")
def list_agent_feedback(
    session_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """List feedback. With ``session_id`` returns that session's ratings
    (used to initialize the per-item thumbs in the UI); otherwise the global
    history the agent can learn from."""
    fb = agentic.AgentFeedback(DB_PATH)
    if session_id:
        if not agentic.AgentSessionStore(DB_PATH).get(session_id):
            raise HTTPException(status_code=404, detail="agent session not found")
        if agentic.AgentSessionStore(DB_PATH).get(session_id).get("incognito"):
            # Incognito sessions can never hold feedback.
            entries: list[dict[str, Any]] = []
        else:
            entries = fb.get_for_session(session_id)
    else:
        entries = fb.list(limit=limit)
    return {"feedback": entries}


@app.delete("/agent/feedback", status_code=204, response_model=None)
def delete_agent_feedback(
    session_id: str = Query(...),
    video_id: str = Query(...),
    source: Literal["frame", "audio"] = Query(...),
    timestamp: float = Query(...),
) -> None:
    """Remove feedback for one item (un-rate)."""
    if not agentic.AgentFeedback(DB_PATH).delete(session_id, video_id, source, timestamp):
        raise HTTPException(status_code=404, detail="feedback not found")


# --------------------------------------------------------------------------- #
# Transcription job endpoints (resumable chunked worker)
# --------------------------------------------------------------------------- #


@app.post("/videos/{video_id}/transcribe", status_code=201)
async def create_transcription_job(video_id: str) -> dict[str, Any]:
    """Create a chunked transcription job for the given video.

    The job splits the video into 30-second chunks and processes each
    incrementally so progress is preserved on interrupt/restart.
    """
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT id, duration, status FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="video not found")

        # Gate: cannot transcribe until video is transcoded.
        if row["status"] != "transcoded":
            raise HTTPException(
                400,
                detail=f"cannot transcribe: video status is '{row['status']}' "
                "(must be 'transcoded')",
            )

        duration = row["duration"] or 0.0
        if duration <= 0:
            raise HTTPException(400, detail="video has unknown or zero duration")

        # Don't create a new job if one is in-flight or already done.
        existing = conn.execute(
            "SELECT id, status FROM transcription_jobs"
            " WHERE video_id = ? AND status IN ('pending', 'running', 'completed')",
            (video_id,),
        ).fetchone()
        if existing:
            raise HTTPException(
                409,
                detail=f"transcription job {existing['id']} already exists (status: {existing['status']})",
            )

        cfg = get_ai_config()
        chunk_size = cfg.audio_chunk_duration
        num_chunks = max(1, int(-(-duration // chunk_size)))  # ceiling division

        job_id = uuid.uuid4().hex
        now = _now_iso()
        conn.execute(
            """INSERT INTO transcription_jobs
               (id, video_id, status, total_chunks, current_chunk_index,
                options, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job_id, video_id, "queued", num_chunks, -1,
             json.dumps({"frame_interval": cfg.frame_interval,
                         "chunk_duration": chunk_size}),
             now, now),
        )

        for i in range(num_chunks):
            start_s = i * chunk_size
            end_s = min(start_s + chunk_size, duration)
            conn.execute(
                """INSERT INTO transcription_job_chunks
                   (job_id, chunk_index, start_seconds, end_seconds, status)
                   VALUES (?,?,?,?,?)""",
                (job_id, i, start_s, end_s, "pending"),
            )
        conn.commit()

    return {"job_id": job_id, "status": "queued", "total_chunks": num_chunks}


@app.get("/transcribe/jobs/{job_id}")
def get_transcription_job(job_id: str) -> dict[str, Any]:
    """Return the job status and per-chunk progress."""
    with closing(get_db()) as conn:
        job = conn.execute(
            "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        chunks = conn.execute(
            "SELECT * FROM transcription_job_chunks WHERE job_id = ? ORDER BY chunk_index",
            (job_id,),
        ).fetchall()
    return {
        "job": dict(job),
        "chunks": [dict(c) for c in chunks],
    }


@app.post("/transcribe/jobs/{job_id}/resume")
def resume_transcription_job(job_id: str) -> dict[str, str]:
    """Reset a failed/pending job so the worker picks it up again."""
    with closing(get_db()) as conn, conn:
        job = conn.execute(
            "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job["status"] not in ("pending", "failed"):
            raise HTTPException(
                400, detail=f"job status is '{job['status']}' — cannot resume"
            )
        now = _now_iso()
        conn.execute(
            "UPDATE transcription_jobs SET status = 'queued', current_chunk_index = -1,"
            " error_message = NULL, updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        conn.execute(
            "UPDATE transcription_job_chunks SET status = 'pending',"
            " error_message = NULL, completed_at = NULL"
            " WHERE job_id = ? AND status IN ('failed', 'running')",
            (job_id,),
        )
    return {"job_id": job_id, "status": "queued"}


# --------------------------------------------------------------------------- #
# Background transcription worker
# --------------------------------------------------------------------------- #


async def _transcription_worker_loop() -> None:
    """Background loop that picks up pending jobs and processes them."""
    while True:
        try:
            job = _pick_pending_job()
            if job is not None:
                async with _transcribe_sem:
                    await _process_job(job["id"])
            else:
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(5.0)


def _pick_pending_job() -> dict[str, Any] | None:
    """Return the oldest pending transcription job, or None."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT * FROM transcription_jobs WHERE status = 'queued'"
            " ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


async def _process_job(job_id: str) -> None:
    """Process all non-completed chunks of a job sequentially."""
    now = _now_iso()
    with closing(get_db()) as conn, conn:
        conn.execute(
            "UPDATE transcription_jobs SET status = 'running', updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        # Also mark the video's transcription status.
        conn.execute(
            "UPDATE videos SET transcription_status = 'transcripting'"
            " WHERE id = (SELECT video_id FROM transcription_jobs WHERE id = ?)",
            (job_id,),
        )
        conn.commit()

    with closing(get_db()) as conn:
        job = conn.execute(
            "SELECT v.id AS video_id, v.stored_name, j.total_chunks, j.options"
            " FROM transcription_jobs j JOIN videos v ON v.id = j.video_id"
            " WHERE j.id = ?",
            (job_id,),
        ).fetchone()
        if job is None:
            return
        video_id = job["video_id"]
        video_path = UPLOAD_DIR / job["stored_name"]
        if not video_path.exists():
            _fail_job(job_id, "video file not found on disk")
            return
        opts = json.loads(job["options"] or "{}")
        frame_interval = opts.get("frame_interval", 1)
        chunk_duration = opts.get("chunk_duration", 30)
        cfg = get_ai_config()

        chunks = conn.execute(
            "SELECT * FROM transcription_job_chunks"
            " WHERE job_id = ? ORDER BY chunk_index",
            (job_id,),
        ).fetchall()

    _running_transcribe_jobs[video_id] = job_id
    log.info(
        "[transcribe] starting job_id=%s video_id=%s total_chunks=%d",
        job_id, video_id, job["total_chunks"],
    )
    try:
        vlm = vlm_client()
        asr = asr_client()

        for chunk in chunks:
            # Graceful abort if the video was deleted while we were processing.
            if video_id in _cancelled_video_ids:
                return

            if chunk["status"] == "completed":
                continue

            work_dir = Path(tempfile.mkdtemp(prefix=f"transcribe_{video_id}_{job_id}_"))
            try:
                now = _now_iso()
                with closing(get_db()) as conn, conn:
                    conn.execute(
                        "UPDATE transcription_job_chunks SET status = 'running'"
                        " WHERE id = ?",
                        (chunk["id"],),
                    )
                    conn.execute(
                        "UPDATE transcription_jobs SET current_chunk_index = ?, updated_at = ?"
                        " WHERE id = ?",
                        (chunk["chunk_index"], now, job_id),
                    )
                    conn.commit()

                cs = float(chunk["start_seconds"])
                ce = float(chunk["end_seconds"])
                dur = ce - cs

                # --- Frame descriptions ---
                frames = extract_frames_for_interval(
                    video_path, work_dir, cs, dur, frame_interval
                )
                log.info(
                    "[transcribe] video_id=%s chunk=%d/%d frames=%d start=%.3fs end=%.3fs",
                    video_id, chunk["chunk_index"], job["total_chunks"], len(frames), cs, ce,
                )
                for frm in frames:
                    desc = await asyncio.to_thread(vlm.describe, frm["path"])
                    with closing(get_db()) as conn:
                        conn.execute(
                            "INSERT OR IGNORE INTO frame_descriptions (video_id, timestamp, description)"
                            " VALUES (?,?,?)",
                            (video_id, frm["timestamp"], desc),
                        )
                        conn.commit()

                # --- Audio transcription ---
                audio_path = extract_audio_for_interval(video_path, work_dir, cs, dur)
                segments = await asyncio.to_thread(asr.transcribe, audio_path)
                log.info(
                    "[transcribe] video_id=%s chunk=%d/%d audio_segments=%d",
                    video_id, chunk["chunk_index"], job["total_chunks"], len(segments),
                )
                for seg in segments:
                    with closing(get_db()) as conn:
                        conn.execute(
                            "INSERT OR IGNORE INTO audio_transcriptions"
                            " (video_id, segment_index, start_seconds, end_seconds, text)"
                            " VALUES (?,?,?,?,?)",
                            (video_id, seg["index"],
                             seg["start_seconds"], seg["end_seconds"],
                             seg["text"]),
                        )
                        conn.commit()

                now = _now_iso()
                with closing(get_db()) as conn, conn:
                    conn.execute(
                        "UPDATE transcription_job_chunks SET status = 'completed',"
                        " completed_at = ? WHERE id = ?",
                        (now, chunk["id"]),
                    )
                    conn.execute(
                        "UPDATE transcription_jobs SET current_chunk_index = ?, updated_at = ?"
                        " WHERE id = ?",
                        (chunk["chunk_index"], now, job_id),
                    )
                    # Compute transcription progress percentage
                    completed = conn.execute(
                        "SELECT COUNT(*) AS cnt FROM transcription_job_chunks"
                        " WHERE job_id = ? AND status = 'completed'",
                        (job_id,),
                    ).fetchone()["cnt"]
                    total = job["total_chunks"]
                    progress = (completed / total) * 100.0 if total > 0 else 0.0
                    conn.execute(
                        "UPDATE videos SET transcription_progress = ? WHERE id = ?",
                        (progress, video_id),
                    )
                    conn.commit()

            except Exception as exc:
                err_msg = str(exc)
                with closing(get_db()) as conn, conn:
                    conn.execute(
                        "UPDATE transcription_job_chunks SET status = 'failed',"
                        " error_message = ? WHERE id = ?",
                        (err_msg, chunk["id"]),
                    )
                    conn.execute(
                        "UPDATE transcription_jobs SET status = 'failed',"
                        " error_message = ?, updated_at = ? WHERE id = ?",
                        (err_msg, _now_iso(), job_id),
                    )
                    conn.execute(
                        "UPDATE videos SET transcription_status = 'failed',"
                        " transcription_progress = 0.0"
                        " WHERE id = ?",
                        (video_id,),
                    )
                    conn.commit()
                return
            finally:
                if work_dir.exists():
                    shutil.rmtree(work_dir, ignore_errors=True)

        # All chunks completed successfully.
        with closing(get_db()) as conn, conn:
            conn.execute(
                "UPDATE transcription_jobs SET status = 'completed', updated_at = ? WHERE id = ?",
                (_now_iso(), job_id),
            )
            conn.execute(
                "UPDATE videos SET transcription_status = 'transcribed',"
                " transcription_progress = 100.0"
                " WHERE id = ?",
                (video_id,),
            )
            conn.commit()
    finally:
        _running_transcribe_jobs.pop(video_id, None)
        _cancelled_video_ids.discard(video_id)


def _fail_job(job_id: str, message: str) -> None:
    with closing(get_db()) as conn, conn:
        conn.execute(
            "UPDATE transcription_jobs SET status = 'failed', error_message = ?,"
            " updated_at = ? WHERE id = ?",
            (message, _now_iso(), job_id),
        )
        conn.execute(
            "UPDATE videos SET transcription_status = 'failed'"
            " WHERE id = (SELECT video_id FROM transcription_jobs WHERE id = ?)",
            (job_id,),
        )
        conn.commit()


# --------------------------------------------------------------------------- #
# Background transcode worker
# --------------------------------------------------------------------------- #


def _fail_transcode(video_id: str, message: str) -> None:
    """Mark a video's transcode as failed."""
    with closing(get_db()) as conn, conn:
        conn.execute(
            "UPDATE videos SET status = 'failed', transcode_error = ?,"
            " transcode_progress = 0.0 WHERE id = ?",
            (message, video_id),
        )
        conn.commit()


async def _process_transcode_job(
    video_id: str,
    rotation: int,
    mirror: bool,
    has_audio: bool,
) -> None:
    """Background task: transcode raw video to MP4 with progress tracking.

    Reads ffmpeg ``-progress pipe:1`` output to compute a percentage and
    periodically writes it to the DB.  On success the raw file is removed and
    the row updated (stored_name → ``<id>.mp4``, status → transcoded,
    rotation/mirror zeroed because they are baked into pixels).
    """
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT stored_name, duration FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        if row is None:
            return
        raw_filename: str = row["stored_name"]
        duration: float = row["duration"] or 0.0

    raw_path = UPLOAD_DIR / raw_filename
    if not raw_path.exists():
        _fail_transcode(video_id, "raw file not found")
        return

    mp4_path = UPLOAD_DIR / f"{video_id}.mp4"

    # Mark as transcoding.
    with closing(get_db()) as conn, conn:
        conn.execute(
            "UPDATE videos SET status = 'transcoding', transcode_progress = 0.0"
            " WHERE id = ?",
            (video_id,),
        )
        conn.commit()

    log.info("[transcode] starting video_id=%s duration=%.3fs", video_id, duration)

    # Build ffmpeg command (same as transcode_to_mp4 but with -progress pipe:1).
    vf = _transform_filter(rotation, mirror)
    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts",
        "-i", str(raw_path),
    ]
    if vf != "null":
        cmd.extend(["-vf", f"{vf},format=yuv420p"])
    else:
        cmd.extend(["-vf", "format=yuv420p"])
    cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-movflags", "+faststart"])
    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    else:
        cmd.append("-an")
    cmd.extend(["-progress", "pipe:1"])
    cmd.append(str(mp4_path))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        _fail_transcode(video_id, "ffmpeg not found on PATH")
        return

    _running_transcode_procs[video_id] = proc

    last_update = time.time()
    stderr_data: list[str] = []

    async def _read_stderr() -> None:
        nonlocal stderr_data
        raw = (await proc.stderr.read()).decode(errors="replace")
        stderr_data = raw.strip().split("\n")

    stderr_task = asyncio.create_task(_read_stderr())

    try:
        progress_re = re.compile(r"out_time_us=(\d+)")
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode(errors="replace").strip()
            m = progress_re.search(line)
            if m and duration > 0:
                out_time_us = int(m.group(1))
                # out_time_us in microseconds, duration in seconds
                pct = min(out_time_us / (duration * 10_000.0), 100.0)
                now = time.time()
                if now - last_update >= 1.0 or pct >= 100.0:
                    last_update = now
                    log.info(
                        "[transcode] video_id=%s progress=%.1f%%",
                        video_id, pct,
                    )
                    try:
                        with closing(get_db()) as conn:
                            conn.execute(
                                "UPDATE videos SET transcode_progress = ? WHERE id = ?",
                                (round(pct, 1), video_id),
                            )
                            conn.commit()
                    except sqlite3.Error:
                        pass

        await stderr_task
        returncode = await proc.wait()
    except asyncio.CancelledError:
        # Task cancelled (e.g. video deleted during transcode).
        try:
            proc.terminate()
            await proc.wait()
        except ProcessLookupError:
            pass
        # Clean up partial output.
        mp4_path.unlink(missing_ok=True)
        raise
    finally:
        _running_transcode_procs.pop(video_id, None)

    if returncode != 0:
        err_text = "; ".join(stderr_data[-5:]) if stderr_data else "ffmpeg failed"
        _fail_transcode(video_id, err_text)
        mp4_path.unlink(missing_ok=True)
        return

    # Success — remove raw file, probe MP4, update DB.
    raw_path.unlink(missing_ok=True)
    try:
        props = probe_video(mp4_path)
    except RuntimeError:
        props = {}

    with closing(get_db()) as conn, conn:
        conn.execute(
            """UPDATE videos SET
               stored_name = ?, status = 'transcoded', transcode_progress = 100.0,
               rotation = 0, mirror = 0,
               fps = ?, width = ?, height = ?, container = ?, size_bytes = ?
               WHERE id = ?""",
            (
                f"{video_id}.mp4",
                props.get("fps"),
                props.get("width"),
                props.get("height"),
                props.get("container"),
                props.get("size_bytes"),
                video_id,
            ),
        )
        conn.commit()

    # Also update transcription_status if the video was previously transcribed
    # (it won't be for new uploads, but handles the restart-reset case).
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT transcription_status FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        if row and row["transcription_status"] == "transcripting":
            conn.execute(
                "UPDATE videos SET transcription_status = 'untranscribed' WHERE id = ?",
                (video_id,),
            )
            conn.commit()


async def _transcode_worker_loop() -> None:
    """Background loop that picks up 'queued' videos and transcodes them.

    Uses _transcode_sem to limit concurrent transcode jobs to MAX_TRANSCODE_JOBS.
    """
    while True:
        try:
            video = _pick_pending_transcode()
            if video is not None:
                vid = video["id"]
                if vid not in _running_transcode_tasks:
                    task = asyncio.create_task(
                        _transcode_with_semaphore(
                            vid,
                            video["rotation"],
                            bool(video["mirror"]),
                            bool(video["has_audio"]),
                        )
                    )
                    _running_transcode_tasks[vid] = task
                    task.add_done_callback(
                        lambda _t, _vid=vid: _running_transcode_tasks.pop(_vid, None)
                    )
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(5.0)


async def _transcode_with_semaphore(
    video_id: str, rotation: int, mirror: bool, has_audio: bool
) -> None:
    """Transcode a video, holding the semaphore for the duration."""
    async with _transcode_sem:
        await _process_transcode_job(video_id, rotation, mirror, has_audio)


def _pick_pending_transcode() -> dict[str, Any] | None:
    """Return the oldest video with status='queued', or None."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT id, rotation, mirror, has_audio FROM videos"
            " WHERE status = 'queued' ORDER BY upload_time ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def _cleanup_orphan_transcode_tmp() -> None:
    """Remove raw files for videos that are no longer in 'queued' state.

    If a crash left behind ``<id>_raw.*`` files while the video row is already
    transcoded / failed / deleted, they are dead weight.
    """
    with closing(get_db()) as conn:
        queued_ids = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM videos WHERE status = 'queued'"
            ).fetchall()
        }
    for p in UPLOAD_DIR.glob("*_raw.*"):
        vid = p.stem.split("_raw")[0]
        if vid not in queued_ids:
            p.unlink(missing_ok=True)


def cleanup_orphan_disk_files() -> None:
    """Remove disk files in UPLOAD_DIR that have no corresponding DB entry."""
    with closing(get_db()) as conn:
        known = {
            r["stored_name"]
            for r in conn.execute("SELECT stored_name FROM videos").fetchall()
        }
    for p in UPLOAD_DIR.iterdir():
        if p.is_file() and p.name not in known:
            p.unlink(missing_ok=True)


def _cleanup_stale_staging() -> None:
    """Remove staging directories left over from a previous crash."""
    for p in STAGING_DIR.iterdir():
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


# Front-end (served last so it does not shadow the API routes above).
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8090")),
        reload=True,
    )
