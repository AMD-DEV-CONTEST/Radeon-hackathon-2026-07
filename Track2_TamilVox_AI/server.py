"""
TamilVox AI Server — Alexa-Style Home Automation
=================================================
Controls: Light + Fan + AC via HiveMQ MQTT
Language: Tamil + English voice commands
Stack:    Whisper → Sarvam AI → Ollama Llama3 → Sarvam TTS
Run:      uvicorn server:app --host 0.0.0.0 --port 8000
"""

import os, base64, json, tempfile, io, wave, struct
from pathlib import Path
import httpx
import paho.mqtt.client as mqtt
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse
from faster_whisper import WhisperModel

# ──────────────────────────────────────────────────────
# CONFIG ← FILL ALL OF THESE BEFORE RUNNING
# ──────────────────────────────────────────────────────
CONFIG_FILE = Path(__file__).with_name("config.env")


def load_config_file(path: Path = CONFIG_FILE):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_config_file()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "524288"))

# HiveMQ Cloud (free) — signup: hivemq.com/mqtt-cloud-broker
MQTT_BROKER = os.getenv("MQTT_BROKER", "")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

# MQTT Topics — relay ESP32 subscribes to these
TOPIC_LIGHT = "tamilvox/home/light"
TOPIC_FAN = "tamilvox/home/fan"
TOPIC_AC = "tamilvox/home/ac"
TOPIC_STATUS = "tamilvox/home/status"

# Sarvam endpoints
TRANSLATE_URL = "https://api.sarvam.ai/translate"
TTS_URL = "https://api.sarvam.ai/text-to-speech"

# ──────────────────────────────────────────────────────
# WHISPER (AMD ROCm / Radeon GPU Accelerated)
# ──────────────────────────────────────────────────────
try:
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    gpu_name = torch.cuda.get_device_name(0) if device == "cuda" else "CPU (Fallback)"
except Exception:
    device = "cpu"
    compute_type = "int8"
    gpu_name = "CPU (Fallback)"

print(f"[BOOT] Loading Whisper small model on {device.upper()} ({gpu_name})...")
whisper_model = WhisperModel("small", device=device, compute_type=compute_type)
print(f"[BOOT] Whisper ready on {device.upper()}.")

# ──────────────────────────────────────────────────────
# MQTT
# ──────────────────────────────────────────────────────
mqtt_client = mqtt.Client(client_id="tamilvox_server", protocol=mqtt.MQTTv5)
MQTT_ENABLED = bool(MQTT_BROKER and MQTT_USER and MQTT_PASSWORD)

if MQTT_ENABLED:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    mqtt_client.tls_set()


def _on_connect(client, userdata, flags, rc, props=None):
    print(f"[MQTT] {'Connected' if rc == 0 else f'Failed rc={rc}'}")
    if rc == 0:
        client.subscribe(TOPIC_STATUS)


mqtt_client.on_connect = _on_connect

if MQTT_ENABLED:
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"[MQTT] Warning: {e}")
else:
    print("[MQTT] Disabled: broker/user/password missing.")

app = FastAPI(title="TamilVox Home Automation Server")

# ──────────────────────────────────────────────────────
# VOICE COMMAND MAPPINGS  (Tamil + English)
# ──────────────────────────────────────────────────────
HOME_COMMANDS = {
    # ── LIGHT ──
    "light on": ("light", "ON"),
    "turn on light": ("light", "ON"),
    "switch on light": ("light", "ON"),
    "lights on": ("light", "ON"),
    "light off": ("light", "OFF"),
    "turn off light": ("light", "OFF"),
    "switch off light": ("light", "OFF"),
    "lights off": ("light", "OFF"),
    # Tamil
    "விளக்கை போடு": ("light", "ON"),
    "விளக்கு போடு": ("light", "ON"),
    "விளக்கு ஆன்": ("light", "ON"),
    "லைட் போடு": ("light", "ON"),
    "லைட் ஆன்": ("light", "ON"),
    "விளக்கை அணை": ("light", "OFF"),
    "விளக்கு அணை": ("light", "OFF"),
    "விளக்கு ஆஃப்": ("light", "OFF"),
    "லைட் அணை": ("light", "OFF"),
    "லைட் ஆஃப்": ("light", "OFF"),
    # ── FAN ──
    "fan on": ("fan", "ON"),
    "turn on fan": ("fan", "ON"),
    "switch on fan": ("fan", "ON"),
    "fan off": ("fan", "OFF"),
    "turn off fan": ("fan", "OFF"),
    "switch off fan": ("fan", "OFF"),
    "fan slow": ("fan", "SPEED_1"),
    "fan speed 1": ("fan", "SPEED_1"),
    "fan medium": ("fan", "SPEED_2"),
    "fan speed 2": ("fan", "SPEED_2"),
    "fan fast": ("fan", "SPEED_3"),
    "fan speed 3": ("fan", "SPEED_3"),
    "fan full speed": ("fan", "SPEED_3"),
    # Tamil
    "ஃபேன் போடு": ("fan", "ON"),
    "விசிறி போடு": ("fan", "ON"),
    "விசிறி ஆன்": ("fan", "ON"),
    "பங்கா போடு": ("fan", "ON"),
    "ஃபேன் அணை": ("fan", "OFF"),
    "விசிறி அணை": ("fan", "OFF"),
    "விசிறி ஆஃப்": ("fan", "OFF"),
    "பங்கா அணை": ("fan", "OFF"),
    "விசிறி மெதுவாக": ("fan", "SPEED_1"),
    "விசிறி நடுத்தரமாக": ("fan", "SPEED_2"),
    "விசிறி வேகமாக": ("fan", "SPEED_3"),
    # ── AC ──
    "ac on": ("ac", "ON"),
    "turn on ac": ("ac", "ON"),
    "air conditioner on": ("ac", "ON"),
    "ac off": ("ac", "OFF"),
    "turn off ac": ("ac", "OFF"),
    "air conditioner off": ("ac", "OFF"),
    "ac 16": ("ac", "TEMP_16"),
    "ac 18": ("ac", "TEMP_18"),
    "ac 20": ("ac", "TEMP_20"),
    "ac 22": ("ac", "TEMP_22"),
    "ac 24": ("ac", "TEMP_24"),
    "ac 25": ("ac", "TEMP_25"),
    "ac 26": ("ac", "TEMP_26"),
    "ac 28": ("ac", "TEMP_28"),
    "set ac to 24": ("ac", "TEMP_24"),
    "set ac 24": ("ac", "TEMP_24"),
    "ac temperature 24": ("ac", "TEMP_24"),
    # Tamil
    "ஏசி போடு": ("ac", "ON"),
    "குளிர்சாதனம் போடு": ("ac", "ON"),
    "ஏசி அணை": ("ac", "OFF"),
    "குளிர்சாதனம் அணை": ("ac", "OFF"),
    "ஏசி 16 டிகிரி": ("ac", "TEMP_16"),
    "ஏசி 18 டிகிரி": ("ac", "TEMP_18"),
    "ஏசி 20 டிகிரி": ("ac", "TEMP_20"),
    "ஏசி 22 டிகிரி": ("ac", "TEMP_22"),
    "ஏசி 24 டிகிரி": ("ac", "TEMP_24"),
    "ஏசி 25 டிகிரி": ("ac", "TEMP_25"),
    "ஏசி 26 டிகிரி": ("ac", "TEMP_26"),
    "ஏசி 28 டிகிரி": ("ac", "TEMP_28"),
    # ── ALL OFF ──
    "everything off": ("all", "OFF"),
    "turn off everything": ("all", "OFF"),
    "all off": ("all", "OFF"),
    "எல்லாவற்றையும் அணை": ("all", "OFF"),
    "அனைத்தும் அணை": ("all", "OFF"),
    "எல்லாம் அணை": ("all", "OFF"),
}

# Tamil voice confirmations
CONFIRMATIONS = {
    ("light", "ON"): "விளக்கை போட்டுவிட்டேன்.",
    ("light", "OFF"): "விளக்கை அணைத்துவிட்டேன்.",
    ("fan", "ON"): "விசிறியை போட்டுவிட்டேன்.",
    ("fan", "OFF"): "விசிறியை அணைத்துவிட்டேன்.",
    ("fan", "SPEED_1"): "விசிறியை மெதுவாக போட்டுவிட்டேன்.",
    ("fan", "SPEED_2"): "விசிறியை நடுத்தர வேகத்தில் போட்டுவிட்டேன்.",
    ("fan", "SPEED_3"): "விசிறியை வேகமாக போட்டுவிட்டேன்.",
    ("ac", "ON"): "ஏசியை போட்டுவிட்டேன்.",
    ("ac", "OFF"): "ஏசியை அணைத்துவிட்டேன்.",
    ("ac", "TEMP_16"): "ஏசியை 16 டிகிரிக்கு வைத்துவிட்டேன்.",
    ("ac", "TEMP_18"): "ஏசியை 18 டிகிரிக்கு வைத்துவிட்டேன்.",
    ("ac", "TEMP_20"): "ஏசியை 20 டிகிரிக்கு வைத்துவிட்டேன்.",
    ("ac", "TEMP_22"): "ஏசியை 22 டிகிரிக்கு வைத்துவிட்டேன்.",
    ("ac", "TEMP_24"): "ஏசியை 24 டிகிரிக்கு வைத்துவிட்டேன்.",
    ("ac", "TEMP_25"): "ஏசியை 25 டிகிரிக்கு வைத்துவிட்டேன்.",
    ("ac", "TEMP_26"): "ஏசியை 26 டிகிரிக்கு வைத்துவிட்டேன்.",
    ("ac", "TEMP_28"): "ஏசியை 28 டிகிரிக்கு வைத்துவிட்டேன்.",
    ("all", "OFF"): "அனைத்தையும் அணைத்துவிட்டேன்.",
}

TOPIC_MAP = {"light": TOPIC_LIGHT, "fan": TOPIC_FAN, "ac": TOPIC_AC}


def detect_home_command(text: str):
    t = text.lower().strip()
    for kw, action in HOME_COMMANDS.items():
        if kw in t:
            return action
    return None


def publish_mqtt(device: str, command: str):
    if not MQTT_ENABLED:
        print("[MQTT] Skipped publish: MQTT disabled.")
        return
    if not mqtt_client.is_connected():
        print("[MQTT] Skipped publish: MQTT disconnected.")
        return

    payload = json.dumps({"device": device, "command": command})
    if device == "all":
        for topic in [TOPIC_LIGHT, TOPIC_FAN, TOPIC_AC]:
            mqtt_client.publish(topic, json.dumps({"command": "OFF"}), qos=1)
        print("[MQTT] All devices OFF")
    else:
        topic = TOPIC_MAP.get(device)
        if topic:
            mqtt_client.publish(topic, payload, qos=1)
            print(f"[MQTT] {topic} → {payload}")


# ──────────────────────────────────────────────────────
# AI HELPERS
# ──────────────────────────────────────────────────────
def transcribe(wav_path):
    segs, info = whisper_model.transcribe(wav_path, beam_size=5)
    text = " ".join([s.text for s in segs]).strip()
    print(f"[STT] '{text}' lang={info.language}")
    return text, info.language


def translate(text, src, tgt):
    if not SARVAM_API_KEY:
        raise HTTPException(500, "SARVAM_API_KEY is not configured.")
    hdrs = {"api-subscription-key": SARVAM_API_KEY, "Content-Type": "application/json"}
    body = {
        "input": text,
        "source_language_code": src,
        "target_language_code": tgt,
        "speaker_gender": "Male",
        "mode": "formal",
        "model": "mayura:v1",
    }
    with httpx.Client(timeout=30) as c:
        r = c.post(TRANSLATE_URL, headers=hdrs, json=body)
        r.raise_for_status()
        return r.json().get("translated_text", text)


def ollama(prompt):
    body = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "prompt": f"You are TamilVox, a helpful Tamil home assistant. Reply concisely in 1-2 sentences.\n\nUser: {prompt}\nAssistant:",
    }
    with httpx.Client(timeout=60) as c:
        r = c.post(f"{OLLAMA_BASE_URL}/api/generate", json=body)
        r.raise_for_status()
        return r.json().get("response", "").strip()


def tts(text, lang="ta-IN"):
    if not SARVAM_API_KEY:
        raise HTTPException(500, "SARVAM_API_KEY is not configured.")
    hdrs = {"api-subscription-key": SARVAM_API_KEY, "Content-Type": "application/json"}
    body = {
        "inputs": [text],
        "target_language": lang,
        "speaker": "anushka",
        "pitch": 0,
        "pace": 1.0,
        "loudness": 1.5,
        "speech_sample_rate": 16000,
        "enable_preprocessing": True,
        "model": "bulbul:v2",
    }
    with httpx.Client(timeout=30) as c:
        r = c.post(TTS_URL, headers=hdrs, json=body)
        r.raise_for_status()
        return base64.b64decode(r.json()["audios"][0])


# ──────────────────────────────────────────────────────
# ENDPOINTS
# ──────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    """Serves the TamilVox AI Web Dashboard UI."""
    dash_file = Path(__file__).with_name("dashboard.html")
    if dash_file.exists():
        return dash_file.read_text(encoding="utf-8")
    return "<h1>TamilVox AI Server Running</h1>"


@app.post("/process")
async def process_audio(
    audio: UploadFile = File(...),
    include_audio: bool = Form(True),
):
    """
    Main endpoint — called by ESP32.
    Returns: {user_text, reply_text, audio_b64, is_command, device, command}
    """
    upload_bytes = await audio.read(MAX_UPLOAD_BYTES + 1)
    if len(upload_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Audio upload is larger than {MAX_UPLOAD_BYTES} bytes.")
    if len(upload_bytes) < 44:
        raise HTTPException(400, "Audio upload is too small to be a WAV file.")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(upload_bytes)
        path = tmp.name

    try:
        user_text, lang = transcribe(path)
        if not user_text:
            raise HTTPException(400, "Could not transcribe.")

        # Translate to English for command matching
        en_text = translate(user_text, "ta-IN", "en-IN") if "ta" in lang else user_text
        print(f"[PROC] English: '{en_text}'")

        # Check home command (check both original and translated)
        action = detect_home_command(user_text) or detect_home_command(en_text)

        if action:
            device, command = action
            publish_mqtt(device, command)
            tamil_reply = CONFIRMATIONS.get((device, command), "செய்துவிட்டேன்.")
            audio_b64 = base64.b64encode(tts(tamil_reply)).decode() if include_audio else ""
            return JSONResponse(
                {
                    "user_text": user_text,
                    "reply_text": tamil_reply,
                    "audio_b64": audio_b64,
                    "is_command": True,
                    "device": device,
                    "command": command,
                }
            )
        else:
            en_reply = ollama(en_text)
            tamil_reply = translate(en_reply, "en-IN", "ta-IN")
            audio_b64 = base64.b64encode(tts(tamil_reply)).decode() if include_audio else ""
            return JSONResponse(
                {
                    "user_text": user_text,
                    "reply_text": tamil_reply,
                    "audio_b64": audio_b64,
                    "is_command": False,
                    "device": None,
                    "command": None,
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] {e}")
        raise HTTPException(500, str(e))
    finally:
        if os.path.exists(path):
            os.unlink(path)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": OLLAMA_MODEL,
        "sarvam_configured": bool(SARVAM_API_KEY),
        "mqtt_enabled": MQTT_ENABLED,
        "mqtt_connected": mqtt_client.is_connected(),
        "websocket_streaming": True,
    }


# ──────────────────────────────────────────────────────
# WEBSOCKET LOW-LATENCY STREAMING & WAKE-WORD HANDLER
# ──────────────────────────────────────────────────────
WAKE_WORDS = ["hey tamilvox", "tamilvox", "alexa", "hey alexa", "வணக்கம்", "ஹலோ", "ஹே தமிழ்வாக்ஸ்"]


def detect_wake_word(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in WAKE_WORDS)


def create_wav_from_pcm(pcm_data: bytes, sample_rate=16000, channels=1, sample_width=2) -> bytes:
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return wav_buf.getvalue()


async def _process_and_reply_ws(websocket: WebSocket, pcm_bytes: bytes, include_audio: bool = True):
    wav_bytes = create_wav_from_pcm(pcm_bytes)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        tmp_path = tmp.name

    try:
        user_text, lang = transcribe(tmp_path)
        if not user_text:
            await websocket.send_json({"status": "no_speech", "user_text": ""})
            return

        has_wake = detect_wake_word(user_text)
        en_text = translate(user_text, "ta-IN", "en-IN") if "ta" in lang else user_text
        action = detect_home_command(user_text) or detect_home_command(en_text)

        if action:
            device, command = action
            publish_mqtt(device, command)
            tamil_reply = CONFIRMATIONS.get((device, command), "செய்துவிட்டேன்.")
            audio_b64 = base64.b64encode(tts(tamil_reply)).decode() if include_audio else ""
            await websocket.send_json(
                {
                    "status": "success",
                    "wake_detected": has_wake,
                    "user_text": user_text,
                    "reply_text": tamil_reply,
                    "audio_b64": audio_b64,
                    "is_command": True,
                    "device": device,
                    "command": command,
                }
            )
        else:
            en_reply = ollama(en_text)
            tamil_reply = translate(en_reply, "en-IN", "ta-IN")
            audio_b64 = base64.b64encode(tts(tamil_reply)).decode() if include_audio else ""
            await websocket.send_json(
                {
                    "status": "success",
                    "wake_detected": has_wake,
                    "user_text": user_text,
                    "reply_text": tamil_reply,
                    "audio_b64": audio_b64,
                    "is_command": False,
                    "device": None,
                    "command": None,
                }
            )
    except Exception as e:
        print(f"[WS Proc Error] {e}")
        await websocket.send_json({"status": "error", "message": str(e)})
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.websocket("/ws/stream")
async def websocket_stream_endpoint(websocket: WebSocket):
    """
    Real-Time Low-Latency Audio Streaming Endpoint over WebSockets.
    Accepts raw 16kHz 16-bit Mono PCM chunks continuously from ESP32 or client.
    Recognizes hands-free Wake-Words ("Hey TamilVox", "வணக்கம்", etc.) and voice commands.
    """
    await websocket.accept()
    print("[WS] Low-Latency PCM Audio Streaming client connected.")
    pcm_buffer = bytearray()

    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"]:
                pcm_buffer.extend(message["bytes"])

                # Auto-process if buffer reaches 3 seconds of 16kHz audio (96,000 bytes)
                if len(pcm_buffer) >= 96000:
                    await _process_and_reply_ws(websocket, bytes(pcm_buffer))
                    pcm_buffer.clear()

            elif "text" in message and message["text"]:
                cmd = message["text"].strip().upper()
                if cmd in ["END", "PROCESS", "SPEAK"]:
                    if len(pcm_buffer) >= 3200:  # >= 100ms
                        await _process_and_reply_ws(websocket, bytes(pcm_buffer))
                    pcm_buffer.clear()
                elif cmd == "CLEAR" or cmd == "RESET":
                    pcm_buffer.clear()
                    await websocket.send_json({"status": "buffer_cleared"})

    except WebSocketDisconnect:
        print("[WS] Client disconnected.")
    except Exception as e:
        print(f"[WS Exception] {e}")


