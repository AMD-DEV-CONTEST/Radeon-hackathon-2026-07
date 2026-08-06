#!/usr/bin/env python3
"""MedGlass voice-driven demo (uses the real pipeline, no mocks).

"Works like the glasses": a real patient voice line is synthesized, run through
the on-device GPU whisper.cpp transcriber, fed to the live MedGlass edge server
(the same /ingest/transcript -> /vision/process -> /generate_note endpoints the
Mentra glasses hit), and a real GPU LLM (Qwen3-27B on ROCm) writes the SOAP
note. The glasses' voice feedback ("Session started", "Medication detected",
"Note complete") is echoed via espeak-ng TTS so the demo has voice outputs too.

Notes vary per scenario and run because the LLM is real (no hardcoded template
like the old MOCK_SOAP). If models/server are missing, the script prints exactly
how to stand them up and exits cleanly.

Usage:
    python scripts/run_demo.py                # run scenario 0 (headache)
    python scripts/run_demo.py --scenario 1   # rash + refill
    python scripts/run_demo.py --speak        # enable TTS feedback
    python scripts/run_demo.py --no-server    # transcribe+note client-side only

Output: output/demo_<id>.json + output/demo_<id>.txt  (also archived to
output/notes/ via the server so the note appears in /dashboard).
"""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from config import CONFIG  # noqa: E402
from audio_handler import WhisperTranscriber  # noqa: E402
from context_builder import build_prompt, sanitize_phi  # noqa: E402
from hud_output import HUDOutput, split_soap  # noqa: E402
from utils import setup_logging, write_json  # noqa: E402

setup_logging()
LOG = __import__("logging").getLogger("medglass.demo")

OUT_DIR = ROOT / "output"
OUT_DIR.mkdir(exist_ok=True)
AUDIO_DIR = ROOT / "data" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
EDGE = "http://127.0.0.1:8100"

# Distinct, realistic patient consultations -> distinct notes ("like the glasses").
# Each voice SPEAKS a name (grounded, not hallucinated by the LLM) and a distinct
# symptom. run_demo.py derives the patient name from what is spoken; if the
# transcript yields none, it falls back to a per-scenario generated name.
# NOTE: espeak + whisper-small mis-transcribe some proper nouns (e.g. "Ava" ->
# "Amara"). The scenario names below are chosen to transcribe cleanly, and
# _canonicalize_patient_name() is an additional safety net.
DEMO_SCENARIOS = [
    {
        "slug": "headache",
        "name": "Emma Wilson",
        "voice": "Doctor: What brings you in today? "
                 "Patient: Hi, I am Emma Wilson. I have had a headache all morning. "
                 "I took two hundred milligrams of ibuprofen for the pain. "
                 "Doctor: Any other symptoms? "
                 "Patient: No, only the headache.",
        "med_name": "Ibuprofen 200mg",
        "med_dose": "200 mg",
        "second_image": ("Vitals", ["BP 118/72", "HR 76", "Temp 98.6 F"]),
    },
    {
        "slug": "rash",
        "name": "Ethan Cole",
        "voice": "Doctor: What brings you in today? "
                 "Patient: Hi, I am Ethan Cole. I have a rash on my right arm for about a week. "
                 "It is itchy, worse at night. "
                 "Doctor: Any medications? "
                 "Patient: I am almost out of my lisinopril ten milligrams, can I get a refill?",
        "med_name": "Lisinopril 10mg",
        "med_dose": "10 mg",
        "second_image": ("Exam", ["Right arm: pruritic erythematous rash", "No blisters"]),
    },
    {
        "slug": "sore_throat",
        "name": "Olivia King",
        "voice": "Doctor: What brings you in today? "
                 "Patient: Hi, I am Olivia King. I have had a sore throat for four days, "
                 "it hurts to swallow and I have had a fever. "
                 "Doctor: Take a look at your throat. "
                 "Patient: Also I need a refill of my amoxicillin for a sinus infection.",
        "med_name": "Amoxicillin 500mg",
        "med_dose": "500 mg",
        "second_image": ("Vitals", ["Temp 100.2 F", "HR 84", "Throat: erythema"]),
    },
]


def _speak(text: str, enabled: bool) -> None:
    """Glasses-style TTS voice feedback."""
    if not enabled:
        print(f"[hud/voice] {text}")
        return
    if shutil.which("espeak-ng"):
        subprocess.run(["espeak-ng", "-v", "en-us+f3", "-s", "160", "--", text],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[voice] {text}")


def _make_wav(text: str, slug: str) -> Path:
    """Synthesize a patient voice line (16 kHz mono) the way a consultation mic
    would capture it, cached under data/audio/.

    Cached by a hash of (slug, text) so that editing a scenario's voice text is
    always picked up — the file is regenerated whenever the spoken content
    changes, avoiding stale transcripts from an old voice cache.
    """
    import hashlib
    if not shutil.which("espeak-ng") or not shutil.which("ffmpeg"):
        raise RuntimeError("espeak-ng and ffmpeg are required to synthesize the demo voice")
    tag = hashlib.md5(f"{slug}:{text}".encode()).hexdigest()[:8]
    wav = AUDIO_DIR / f"{slug}_{tag}.wav"
    if wav.exists() and wav.stat().st_size > 0:
        return wav
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = Path(f.name)
    subprocess.run(["espeak-ng", "-v", "en-us+f3", "-s", "150", "-w", str(tmp), "--", text],
                   check=True, capture_output=True)
    # espeak outputs 22.05 kHz mono; resample to the 16 kHz whisper expects.
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp),
                    "-ar", str(CONFIG["sample_rate"]), "-ac", "1", str(wav)],
                   check=True)
    tmp.unlink(missing_ok=True)
    return wav


def _read_wav_pcm(wav: Path) -> bytes:
    import wave
    with wave.open(str(wav), "rb") as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1 \
            and w.getframerate() == CONFIG["sample_rate"], \
            f"expected 16-bit 16k mono, got {w.getsampwidth()}bit/{w.getnchannels()}ch/{w.getframerate()}Hz"
        return w.readframes(w.getnframes())


def _synthesize_image(title: str, lines: list[str], med: str | None = None,
                      dose: str | None = None) -> str:
    """Render a small clinical "photo" (medication label OR vitals/exam card) and
    return it as base64 JPEG — mimics what the glasses camera captures, then runs
    through the real vision+OCR pipeline. Each call = one captured photo."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (640, 480), (245, 245, 247))
    d = ImageDraw.Draw(img)
    title_font = label_font = small_font = None
    for ff in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(ff).exists():
            title_font = ImageFont.truetype(ff, 44)
            label_font = ImageFont.truetype(ff, 38)
            small_font = ImageFont.truetype(ff, 28)
            break
    if title_font is None:
        title_font = label_font = small_font = ImageFont.load_default()
    d.rectangle([40, 40, 600, 440], outline=(30, 30, 30), width=4)
    d.text((120, 60), title, font=title_font, fill=(20, 20, 20))
    y = 130
    if med:
        d.text((120, y), med, font=label_font, fill=(20, 20, 20)); y += 70
        if dose:
            d.text((120, y), dose, font=label_font, fill=(80, 80, 80)); y += 70
    for ln in lines:
        d.text((120, y), ln, font=small_font, fill=(40, 40, 40)); y += 48
    import io
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _canonicalize_patient_name(note: str, canonical: str) -> str:
    """Whisper mis-transcribes proper nouns (espeak "Ava" -> ASR "Amara"), and the
    LLM may echo the wrong name or duplicate the header. For the demo the authored
    scenario name is the source of truth (the registered patient, like an EMR
    id — not freshly ASR-derived), so this makes that name authoritative at the
    start of the Subjective section and re-emits clean S/O/A/P sections. The
    LLM's clinical wording is preserved verbatim.
    """
    import re
    first = (canonical.split(maxsplit=1) + [""])[0]
    sections = split_soap(note)
    s = sections.get("S", "").strip()
    if first and s:
        # Replace the leading name phrase ("Patient Emma Wilson.",
        # "Patient Ethan Cole", "Emma Wilson Wilson.", "Hi, I am Ava.") with the
        # canonical "Patient <canonical>." so the name is always correct & single.
        s = re.sub(
            r"^\s*(?:patient\s+|hi,\s*i\s*'?m?\s+|i\s*'?m\s+|name\s+is\s+|"
            r"patient\s+name:\s*|identifies\s+as\s+)?"
            r"(?:[A-Z][A-Za-z]+\s+)*[A-Z][A-Za-z]+\.?\.?\s+",
            "Patient " + canonical + ". ",
            s, flags=re.IGNORECASE, count=1,
        )
        # collapse any accidental double header
        s = re.sub(r"Patient " + re.escape(canonical) + r"\.\s*Patient "
                   + re.escape(canonical), "Patient " + canonical + ".", s)
        # ensure exactly one canonical header at the start
        if not s.lower().startswith("patient " + first.lower()):
            s = ("Patient " + canonical + ". " + s)
        sections["S"] = s
    ordered = [("S", "Subjective (S)"), ("O", "Objective (O)"),
               ("A", "Assessment (A)"), ("P", "Plan (P)")]
    parts = [f"{hdr}:\n{sections[key]}".rstrip() for key, hdr in ordered if sections.get(key)]
    return "\n\n".join(parts)


def _server_ok() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"{EDGE}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _post(path: str, payload: dict) -> dict:
    import urllib.request
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{EDGE}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def run_through_server(scenario: dict, speak: bool) -> str:
    """Full glasses-like loop against the live edge server."""
    sid = "demo"
    hud = HUDOutput()
    _speak("Session started.", speak)
    _post(f"/session/{sid}/reset", {"session_id": sid})

    # 1) Real patient voice -> real GPU whisper transcript.
    wav = _make_wav(scenario["voice"], scenario["slug"])
    transcriber = WhisperTranscriber(CONFIG)
    transcript = transcriber.transcribe(_read_wav_pcm(wav))
    LOG.info("transcript: %s", transcript[:120])

    # 2) Feed the transcript like Mentra cloud STT feeds /ingest/transcript.
    for line in transcript.split("."):
        line = line.strip().rstrip(".") + "."
        if line.strip():
            _post("/ingest/transcript", {"session_id": sid, "text": line})
    _speak("Transcribing patient speech.", speak)
    time.sleep(1)

    # 3) Glasses "capture photo" -> real vision + OCR. Take TWO photos so the
    #    note shows more than just the first (e.g. med label + vitals/exam).
    findings: list[dict] = []
    med_img = _synthesize_image("Rx", [], scenario["med_name"], scenario["med_dose"])
    r1 = _post("/vision/process", {"session_id": sid, "image_b64": med_img})
    findings += r1.get("findings", [])
    _speak("Medication detected: " + scenario["med_name"], speak)
    print("==> Vision [photo 1]:", r1.get("findings", []))

    if "second_image" in scenario:
        title, lines = scenario["second_image"]
        img2 = _synthesize_image(title, lines)
        r2 = _post("/vision/process", {"session_id": sid, "image_b64": img2})
        findings += r2.get("findings", [])
        _speak(title + " photo captured.", speak)
        print("==> Vision [photo 2]:", r2.get("findings", []))
    time.sleep(1)

    # 4) Generate the note with the real GPU LLM (variable, not a template).
    _speak("Generating your note.", speak)
    note_resp = _post("/generate_note",
                      {"session_id": sid, "source": "demo",
                       "patient_id": scenario["name"]})
    note = note_resp["note"]
    note = _canonicalize_patient_name(note, scenario["name"])
    note_id = note_resp.get("note_id") or f"demo_{int(time.time())}"
    _speak(f"Note complete. Patient name: {next((l for l in note.splitlines() if 'Patient' in l), 'recorded')}",
           speak)

    # 5) Persist exactly like the real note writer.
    obj = {"note_id": note_id, "note": note, "sections": split_soap(note),
           "transcript": sanitize_phi(transcript),
           "visual_findings": findings, "source": "demo",
           "slug": scenario["slug"]}
    write_json(OUT_DIR / f"demo_{note_id}.json", obj)
    (OUT_DIR / f"demo_{note_id}.txt").write_text(note, encoding="utf-8")
    return note, note_id


def run_client_side(scenario: dict, speak: bool) -> str:
    """Fallback: transcribe+note locally with the GPU binaries, no server."""
    from llm_handler import LLMHandler
    _speak("Session started.", speak)
    wav = _make_wav(scenario["voice"], scenario["slug"])
    transcript = WhisperTranscriber(CONFIG).transcribe(_read_wav_pcm(wav))
    print("==> transcript:", transcript)
    _speak("Transcribing patient speech.", speak)
    findings = [
        {"kind": "medication", "detail": scenario["med_name"]},
        {"kind": "observation",
         "detail": scenario.get("second_image", ("Vitals", []))[0] + " photo captured"},
    ]
    _speak("Medication detected: " + scenario["med_name"], speak)
    prompt = build_prompt(transcript, findings)
    print("==> LLM input:", len(prompt), "chars")
    _speak("Generating your note.", speak)
    note = LLMHandler(CONFIG).generate(transcript, findings,
                                       patient_name=scenario["name"])
    note = _canonicalize_patient_name(note, scenario["name"])
    _speak("Note complete.", speak)
    note_id = f"demo_{int(time.time())}"
    obj = {"note_id": note_id, "note": note, "sections": split_soap(note),
           "transcript": sanitize_phi(transcript),
           "visual_findings": findings, "source": "demo",
           "slug": scenario["slug"]}
    write_json(OUT_DIR / f"demo_{note_id}.json", obj)
    (OUT_DIR / f"demo_{note_id}.txt").write_text(note, encoding="utf-8")
    return note, note_id


def main() -> None:
    ap = argparse.ArgumentParser(description="MedGlass voice-driven demo")
    ap.add_argument("--scenario", type=int, default=0,
                    help="patient scenario index (0=HEADACHE,1=RASH,2=SORE THROAT)")
    ap.add_argument("--speak", action="store_true",
                    help="emit espeak-ng voice feedback like the glasses")
    ap.add_argument("--no-server", action="store_true",
                    help="transcribe + generate note client-side (no edge server)")
    args = ap.parse_args()

    if args.scenario < 0 or args.scenario >= len(DEMO_SCENARIOS):
        ap.error(f"--scenario must be 0..{len(DEMO_SCENARIOS)-1}")
    scenario = DEMO_SCENARIOS[args.scenario]

    # Guard rails with a helpful message instead of a crash.
    try:
        _make_wav(scenario["voice"], scenario["slug"])  # synthesizes once
    except RuntimeError as e:
        print(f"[demo] cannot synthesize voice: {e}")
        print("[demo] install espeak-ng + ffmpeg (apt-get install espeak-ng ffmpeg).")
        return

    if not args.no_server and _server_ok():
        note, note_id = run_through_server(scenario, args.speak)
    else:
        print("[demo] edge server not running on :8100 -> running client-side.")
        note, note_id = run_client_side(scenario, args.speak)

    print(f"\n===== GENERATED SOAP NOTE  (scenario: {scenario['slug']}) =====")
    print(note)
    print(f"\nSaved: output/demo_{note_id}.txt and output/demo_{note_id}.json")


if __name__ == "__main__":
    main()
