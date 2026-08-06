"""GraphVoice API server with WebSocket continuous listening."""

import base64
import json as json_module
import os
import queue
import tempfile
import threading
import uuid

from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from flask_sock import Sock

from audio.stream_handler import StreamHandler, process_turn_text, process_utterance
from diary import runtime
from diary.image_agent import ImageAgent, MEDIA_ROOT, read_day_rich
from diary.tools import DiaryContext
from diary.day_view import get_day_view
from diary.article import generate_article
from tts.kokoro_tts import synthesize
from utils.logger import setup_logging

logger = setup_logging("server")

app = Flask(__name__, static_folder="frontend", static_url_path="")
CORS(app)
sock = Sock(app)

# Never cache the frontend in dev — otherwise the browser replays a stale
# graph-face.js (Flask defaults to a 12h max-age) and the UI looks unchanged
# after an edit. Audio responses below set their own cache headers.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Spoken to the user when a turn fails for a reason they cannot act on (database
# down, API quota, STT outage). Deliberately vague and short: it is read aloud.
TURN_FAILED_MESSAGE = "抱歉，这次没能处理成功，请再说一次。"

# In-memory audio cache
_audio_cache: dict[str, str] = {}
# Active stream handlers per WebSocket connection
_streamers: dict[str, StreamHandler] = {}
# Selected diary day per WebSocket connection (set by the client's date-nav).
_session_dates: dict[str, str] = {}

# ─── Background image-generation worker ───────────────────────────────
# Image generation (Z-Image-Turbo via the :8090 service + 35B judge) is slow and
# must NEVER sit on the voice/TTS request path. We enqueue a (date, force) job and a
# single daemon thread drains it, so spoken latency is unaffected. The worker is
# created lazily on first enqueue.
_media_q: "queue.Queue" = queue.Queue()
_media_thread: threading.Thread | None = None


def _start_media_worker():
    global _media_thread
    if _media_thread is None:
        _media_thread = threading.Thread(target=_media_worker, daemon=True)
        _media_thread.start()


def _media_worker():
    """Drain the media queue: generate poster + thumbnails for each day.

    Idempotent + incremental: if a manifest already exists for the day and no new
    entries have appeared, the job is a no-op; otherwise the day is regenerated so
    newly-narrated notable moments get their thumbnails.
    """
    while True:
        job = _media_q.get()
        if job is None:
            break
        date, force = job
        try:
            agent = ImageAgent()
            ctx = DiaryContext(client=runtime.get_client())
            entries = [e for e in read_day_rich(ctx, date) if e["text"].strip()]
            if not entries:
                continue
            manifest_path = os.path.join(MEDIA_ROOT, date, "manifest.json")
            need_force = force
            if not need_force and os.path.isfile(manifest_path):
                with open(manifest_path, encoding="utf-8") as f:
                    existing = json_module.load(f)
                covered = set()
                for item in existing:
                    covered.update(item.get("linked_entry_ids", []))
                if {e["id"] for e in entries} <= covered:
                    continue  # nothing new since last generation
                need_force = True
            agent.generate_for_day(date, ctx, force=need_force)
            logger.info("media generated for day %s (force=%s)", date, need_force)
        except Exception:
            logger.exception("media generation failed for day %s", date)
        finally:
            _media_q.task_done()


def enqueue_media(date: str, force: bool = False) -> None:
    """Enqueue (date, force); starts the worker thread on first call."""
    _start_media_worker()
    _media_q.put((date, force))


def _detect_lang(text: str) -> str:
    chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return "zh" if chinese > len(text) * 0.3 else "en"


def _get_session_id() -> str:
    """Extract session ID from request headers or generate one."""
    sid = request.headers.get("X-Session-Id", "").strip()
    if not sid:
        sid = uuid.uuid4().hex[:12]
    return sid


# ─── Serve frontend ──────────────────────────────────────────────


@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


# ─── Health ──────────────────────────────────────────────────────


@app.route("/api/health")
def health():
    try:
        runtime.get_client().health()
        db_ok = True
    except Exception:
        logger.exception("Bionic-Graph health check failed")
        db_ok = False
    return jsonify({"status": "ok" if db_ok else "degraded", "database": db_ok})


# ─── About (README rendered for the UI) ──────────────────────────


@app.route("/api/about")
def about():
    """Render README.md to HTML so the UI's About modal stays in sync.

    Uses markdown_it (commonmark + tables). The README is a trusted repo file, so
    raw-HTML passthrough is enabled for maximum fidelity.
    """
    try:
        from markdown_it import MarkdownIt
        import os as _os
        import time as _time

        md_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "README.md")
        if not _os.path.isfile(md_path):
            return jsonify({"title": "About", "html": "<p>README.md not found.</p>"})
        with open(md_path, encoding="utf-8") as f:
            raw = f.read()
        html = MarkdownIt("commonmark", {"html": True}).enable(["table"]).render(raw)
        return jsonify(
            {
                "title": "Howdy · About",
                "html": html,
                "updated": _time.strftime("%Y-%m-%d %H:%M", _time.localtime(_os.path.getmtime(md_path))),
            }
        )
    except Exception:
        logger.exception("about failed")
        return jsonify({"title": "About", "html": "<p>Could not load README.</p>"})


# ─── Text query ──────────────────────────────────────────────────


@app.route("/api/ask", methods=["POST"])
def ask():
    data = request.get_json()
    query = (data or {}).get("query", "").strip()
    if not query:
        return jsonify({"error": "Empty query"}), 400

    date = (data or {}).get("date") or request.headers.get("X-Date") or runtime.today_iso()
    lang = (data or {}).get("lang", "zh")

    try:
        sid = _get_session_id()
        result = process_turn_text(query, date=date, session_id=sid, lang=lang)
        answer = result["answer"]
        # Fully-automatic image enrichment: queue poster + thumbnails for the day.
        enqueue_media(date)
        return jsonify(
            {
                "answer": answer,
                "lang": _detect_lang(answer),
                "date": date,
                "session_id": sid,
            }
        )
    except Exception as e:
        logger.exception("Query failed")
        return jsonify({"error": str(e)}), 500


# ─── Voice blob (push-to-talk fallback) ─────────────────────────


@app.route("/api/voice", methods=["POST"])
def voice():
    audio_bytes = _get_audio_bytes()
    if not audio_bytes or len(audio_bytes) < 1000:
        return jsonify({"error": "Audio too short"}), 400

    sid = _get_session_id()
    date = request.headers.get("X-Date") or runtime.today_iso()
    lang = request.headers.get("X-Lang", "zh")

    # The STT client expects a base64 audio blob; the browser may send webm or wav.
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    result = process_utterance(audio_b64, date=date, session_id=sid, lang=lang)
    text = result["text"]
    answer = result["answer"]

    if text and answer:
        # Fully-automatic image enrichment: queue poster + thumbnails for the day.
        enqueue_media(date)

    if not text or not answer:
        # STT disabled/unavailable (no API key) or agent had nothing to say.
        return jsonify({"error": answer or "STT failed", "text": text})

    audio_id = uuid.uuid4().hex
    audio_b64_out = result["audio_b64"]
    perm_path = None
    if audio_b64_out:
        tts_wav = os.path.join(tempfile.gettempdir(), f"graphvoice_{audio_id}.wav")
        with open(tts_wav, "wb") as f:
            f.write(base64.b64decode(audio_b64_out))
        perm_path = tts_wav
        _audio_cache[audio_id] = perm_path

    return jsonify(
        {
            "text": text,
            "answer": answer,
            "lang": _detect_lang(answer),
            "date": date,
            "session_id": sid,
            "audio_id": audio_id if perm_path else None,
        }
    )


# ─── Audio playback ──────────────────────────────────────────────


@app.route("/api/audio/<audio_id>")
def audio(audio_id: str):
    filepath = _audio_cache.get(audio_id)
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "Audio not found"}), 404
    ext = os.path.splitext(filepath)[1]
    mimetype = "audio/wav" if ext == ".wav" else "audio/aiff"
    return send_file(filepath, mimetype=mimetype)


# ─── Generated diary media (images) ──────────────────────────────


@app.route("/media/<path:rel>")
def media_file(rel: str):
    """Serve generated images (posters / thumbnails / comics) from media/<date>/."""
    base = os.path.abspath(MEDIA_ROOT)
    target = os.path.abspath(os.path.join(base, rel))
    if not target.startswith(base + os.sep) and target != base:
        return jsonify({"error": "forbidden"}), 403
    if not os.path.isfile(target):
        return jsonify({"error": "not found"}), 404
    return send_file(target)


def _media_manifest_json(date: str) -> dict:
    """Read the day's manifest and return it with browser-facing image URLs."""
    manifest_path = os.path.join(MEDIA_ROOT, date, "manifest.json")
    if not os.path.isfile(manifest_path):
        return {"date": date, "exists": False, "items": []}
    with open(manifest_path, encoding="utf-8") as f:
        items = json_module.load(f)
    out = []
    for it in items:
        fname = os.path.basename(it.get("image_path", ""))
        url = f"/media/{date}/{fname}" if fname else None
        out.append(
            {
                "type": it.get("type"),
                "image_url": url,
                "summary": it.get("summary"),
                "highlights": it.get("highlights"),
                "caption": it.get("caption"),
                "subject": it.get("subject"),
                "judge_critique": it.get("judge_critique"),
                "seed": it.get("seed"),
            }
        )
    return {"date": date, "exists": True, "items": out}


@app.route("/api/media/<date>")
def media_get(date: str):
    return jsonify(_media_manifest_json(date))


@app.route("/api/media/<date>/generate", methods=["POST"])
def media_generate(date: str):
    """Enqueue (or force) image generation for a day. Non-blocking."""
    data = request.get_json() or {}
    force = bool(data.get("force", False))
    enqueue_media(date, force=force)
    return jsonify({"enqueued": True, "date": date, "force": force})


# ─── Day graph (read-only) + Export ─────────────────────────────


@app.route("/api/day/<date>")
def day_view(date: str):
    """Return the day's graph (entries, entities, todos) + flat entry list."""
    return jsonify(get_day_view(date))


@app.route("/api/day/<date>/export", methods=["POST"])
def day_export(date: str):
    """Rewrite the day's diary as an article in a chosen famous writer's style."""
    data = request.get_json() or {}
    style = (data.get("style") or "").strip()
    lang = data.get("lang", "zh") if data.get("lang") in ("zh", "en") else "zh"
    if not style:
        return jsonify({"article": ""})
    try:
        article = generate_article(date, style, lang)
    except Exception:
        logger.exception("export failed for %s", date)
        article = ""
    return jsonify({"article": article})


# ─── TTS from text ───────────────────────────────────────────────


@app.route("/api/tts", methods=["POST"])
def tts():
    data = request.get_json()
    text = (data or {}).get("text", "").strip()
    lang = (data or {}).get("lang", "zh")
    if not text:
        return jsonify({"error": "Empty text"}), 400

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = synthesize(text, os.path.join(tmpdir, "output"), lang=lang)
        if os.path.exists(audio_path):
            ext = os.path.splitext(audio_path)[1]
            return send_file(audio_path, mimetype="audio/wav" if ext == ".wav" else "audio/aiff")
    return jsonify({"error": "TTS failed"}), 500


# ─── WebSocket: Continuous Listening ─────────────────────────────


@sock.route("/ws/listen")
def ws_listen(ws):
    """Continuous audio streaming with VAD-based speech detection.

    Binary frames are raw int16 mono PCM at 16 kHz. Text frames are JSON control
    messages:

        {"type": "hello", "vad": "client"|"server", "date": "YYYY-MM-DD"}
        {"type": "eou"}                       client-VAD: end of utterance
        {"type": "date", "date": "YYYY-MM-DD"} re-target the diary day
        {"type": "text", "text": "..."}        a client-transcribed turn (local STT)

    A client that runs Silero on WebGPU sends only the audio it already judged to be
    speech and closes each turn with "eou"; everything else falls back to the
    server-side VAD, which sees every chunk. The diary day can be changed at any time
    via the "date" control frame so the user can browse/replay past or future days.
    """
    sid = _get_session_id()
    handler = StreamHandler(sample_rate=16000)
    _streamers[sid] = handler
    _session_dates[sid] = runtime.today_iso()

    logger.info("WebSocket connected: session=%s", sid)

    try:
        while True:
            raw_data = ws.receive()
            if raw_data is None:
                break

            if isinstance(raw_data, str):
                acted = _handle_control(ws, handler, sid, raw_data)
                if acted is not None:
                    # A dict means a client-sent text turn; run it directly.
                    if isinstance(acted, dict):
                        reply_to_text(ws, handler, acted["text"], sid)
                    else:
                        reply_to_utterance(ws, handler, acted, sid)
                continue

            # Anything shorter than one VAD frame (512 samples) cannot be scored.
            if len(raw_data) < 1024:
                continue

            utterance_b64 = handler.add_chunk(raw_data)
            if utterance_b64:
                reply_to_utterance(ws, handler, utterance_b64)

    except Exception as e:
        logger.exception("WebSocket error: %s", e)
    finally:
        _streamers.pop(sid, None)
        _session_dates.pop(sid, None)
        logger.info("WebSocket disconnected: session=%s", sid)


def _date_for(sid: str) -> str:
    return _session_dates.get(sid) or runtime.today_iso()


def reply_to_utterance(ws, handler: StreamHandler, utterance_b64: str, sid: str) -> None:
    """Run one utterance through STT → agent → TTS and send the answer back."""
    logger.info("Utterance detected, processing...")
    ws.send(json_module.dumps({"type": "processing", "state": "thinking"}))
    try:
        result = process_utterance(utterance_b64, date=_date_for(sid), session_id=sid)
    except Exception:
        # One bad turn must not end the session. Left uncaught, the exception
        # unwinds past the receive loop, the socket closes, and the browser sits
        # on "thinking" until its reconnect timer fires — dropping whatever the
        # user said next.
        logger.exception("Utterance processing failed")
        result = {"text": "", "answer": TURN_FAILED_MESSAGE, "audio_b64": None}
    ws.send(
        json_module.dumps(
            {
                "type": "result",
                "text": result.get("text", ""),
                "answer": result.get("answer", ""),
                "audio_b64": result.get("audio_b64"),
            }
        )
    )
    handler.resume()
    # Queue poster + thumbnails for the day (off the request path).
    if result.get("text"):
        enqueue_media(_date_for(sid))


def reply_to_text(ws, handler: StreamHandler, text: str, sid: str) -> None:
    """Run a client-transcribed text turn (local STT) through the diary agent."""
    logger.info("Text turn received, processing...")
    ws.send(json_module.dumps({"type": "processing", "state": "thinking"}))
    try:
        result = process_turn_text(text, date=_date_for(sid), session_id=sid, lang=_detect_lang(text))
    except Exception:
        logger.exception("Text turn processing failed")
        result = {"text": text, "answer": TURN_FAILED_MESSAGE, "audio_b64": None}
    ws.send(
        json_module.dumps(
            {
                "type": "result",
                "text": result.get("text", ""),
                "answer": result.get("answer", ""),
                "audio_b64": result.get("audio_b64"),
            }
        )
    )
    handler.resume()
    # Queue poster + thumbnails for the day (off the request path).
    if result.get("text"):
        enqueue_media(_date_for(sid))


def _handle_control(ws, handler: StreamHandler, sid: str, payload: str):
    """Apply a JSON control frame.

    Returns:
        None                     — no turn to run
        str (base64 WAV)         — a finished audio utterance to process
        {"text": str}            — a client-transcribed text turn to process
    """
    try:
        msg = json_module.loads(payload)
    except ValueError:
        logger.warning("Ignoring non-JSON text frame on /ws/listen")
        return None

    kind = msg.get("type")
    if kind == "hello":
        handler.client_vad = msg.get("vad") == "client"
        if msg.get("date"):
            _session_dates[sid] = msg["date"]
            enqueue_media(msg["date"])
        where = "client" if handler.client_vad else "server"
        logger.info("session=%s VAD runs on the %s, date=%s", sid, where, _session_dates.get(sid))
        ws.send(json_module.dumps({"type": "ready", "vad": where, "date": _session_dates.get(sid)}))
    elif kind == "eou":
        return handler.end_of_utterance()
    elif kind == "date":
        if msg.get("date"):
            _session_dates[sid] = msg["date"]
            logger.info("session=%s day set to %s", sid, msg["date"])
            # Pre-generate this day's images while the user browses it.
            enqueue_media(msg["date"])
            ws.send(json_module.dumps({"type": "date_ack", "date": msg["date"]}))
    elif kind == "text":
        text = (msg.get("text") or "").strip()
        if text:
            return {"text": text}
    else:
        logger.debug("Unknown control frame: %s", kind)
    return None


# ─── Helpers ─────────────────────────────────────────────────────


def _get_audio_bytes():
    if request.data and len(request.data) > 100:
        return request.data
    if request.files:
        f = request.files.get("audio")
        if f:
            return f.read()
    return None


# ─── Main ───────────────────────────────────────────────────────


def main():
    print("=" * 50)
    print("  GraphVoice Server")
    print("  Open http://localhost:8080")
    print("=" * 50)
    # debug=False by default: the Werkzeug reloader (debug=True) breaks the
    # WebSocket upgrade handshake that flask-sock needs for /ws/listen.
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=8080, debug=debug)


if __name__ == "__main__":
    main()
