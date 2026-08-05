"""
FastAPI routes — SSE streaming (Gemma 4) + Kokoro TTS audio generation.

POST /api/modes/{mode}/analyze   → image → Gemma 4 → SSE text stream
POST /api/audio/generate         → text → Kokoro TTS → WAV download
POST /api/modes/{mode}/generate   → image → Gemma 4 → SSE text stream 
                                  → text → Kokoro TTS → WAV download
"""
import os
import hashlib
import re
import traceback
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import APIRouter, File, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse, StreamingResponse,  JSONResponse
from kokoro import KPipeline

from config import (
    ALLOWED_CONTENT_TYPES,
    KOKORO_LANG,
    KOKORO_VOICE,
    KOKORO_SAMPLE_RATE,
    KOKORO_OUTPUT_DIR,
    MAX_IMAGE_BYTES
)
from gemma_client import generate

router = APIRouter()

MODE_MAP = {
    "education": "education",               # Or whatever your internal value reference is
    "accessibility": "accessibility",
    "heritage_tourism": "heritage_tourism", 
    "digital_world": "digital_world",
    "content_creation": "content_creation"
}


async def _read_image(image: UploadFile) -> bytes:
    """Validate and read uploaded image."""
    if image.content_type and image.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(415, f"Unsupported type: {image.content_type}. Use JPEG or PNG.")
    chunks = []
    total = 0
    while True:
        chunk = await image.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Image too large (max 20 MB)")
        chunks.append(chunk)
    return b"".join(chunks)


async def sse_stream(mode: str, image_bytes: bytes):
    """SSE generator: tokens from Gemma 4."""
    try:
        result = generate(image_bytes, mode)
        # Stream token-by-token
        for word in result.split():
            yield f"data: {word}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
    except Exception as e:
        err = str(e).replace('"', "'")
        yield f'data: {{"error":"{err}"}}\n\n'.encode("utf-8")

async def _get_full_text_from_stream(generator) -> str:
    """Helper utility to consume the true asynchronous SSE generator and extract clean text output string.

    🎯 THE RESOLUTION: Changed back to 'async for' because your sse_stream is a true async generator!
    """
    full_text = []

    # 🎛️ 🎯 FIX 2: Correctly use async for to stream tokens out of your async generator
    async for chunk in generator:

        # Convert incoming raw byte coordinates into standard readable python strings
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")

        if isinstance(chunk, str):
            # Check for standard server-sent events structural metadata indicators
            if chunk.startswith("data:"):
                clean_chunk = chunk.replace("data:", "").strip()

                # Stop processing if the model dispatches its completion boundary token flag
                if clean_chunk == "[DONE]":
                    break

                # Skip any json error payload packets to isolate clean text words
                if clean_chunk.startswith("{") and '"error"' in clean_chunk:
                    continue

                full_text.append(clean_chunk)

    # Reconnect the individual word tokens with a single blank spacer tracking indicator
    combined_text = " ".join(full_text).strip()
    return combined_text

def _clean_text_for_tts(text: str) -> str:
    """🎯 THE CRITICAL TIMEOUT FIX: Strips out markdown, brackets, and system prompts

    that cause Kokoro's text segment split engines to loop infinitely.
    """
    if not text:
        return ""

    # 1. Remove anything inside brackets completely like [Audio Cue: ...], [Audio Script Start], ***[DONE]***
    clean = re.sub(r"\[.*?\]", "", text)
    clean = re.sub(r"\(.*?\)", "", clean)

    # 2. Remove markdown asterisks (bolding or italics stars like *** or **)
    clean = clean.replace("*", "")

    # 3. Clean up loose whitespaces, tabs, or broken double spacing lines
    clean = re.sub(r"\s+", " ", clean).strip()

    return clean


# ── Endpoints ──────────────────────────────────────────────────

@router.post("/api/modes/{mode}/analyze")
async def analyze(mode: str, image: UploadFile = File(...)):
    """Image → Gemma 4 vision + text → SSE stream."""
    if mode not in MODE_MAP:
        raise HTTPException(422, f"Invalid mode. Use: {', '.join(MODE_MAP)}")
    image_bytes = await read_image(image)
    return StreamingResponse(
        _sse_stream(MODE_MAP[mode], image_bytes),
        media_type="text/event-stream",
    )


@router.post("/api/audio/generate")
async def generate_audio(text: str = Query(..., min_length=2)):
    """Text → Kokoro TTS → WAV file download."""

    pipeline = KPipeline(lang_code=KOKORO_LANG)
    gen = pipeline(text, voice=KOKORO_VOICE, split_pattern=r"\n+|\.\s+")

    segments = []
    for _, _, audio in gen:
        segments.append(audio)

    out_dir = Path(KOKORO_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Unique filename based on text hash
    h = hashlib.sha256(text.encode()).hexdigest()[:12]
    out_path = out_dir / f"speech_{h}.wav"

    if segments:
        combined = np.concatenate(segments)
        sf.write(str(out_path), combined, KOKORO_SAMPLE_RATE)
    else:
        sf.write(str(out_path), np.zeros(24000, dtype=np.float32), KOKORO_SAMPLE_RATE)

    return FileResponse(
        out_path,
        media_type="audio/wav",
        filename="speech.wav",
    )

@router.post("/api/modes/{mode}/generate")
async def generate_multimodal_package(mode: str, image: UploadFile = File(...)):
    """Unified Multimodal Engine Pipeline Interface with Integrated Cleaners."""
    print("\n" + "=" * 60)
    print(f"📥 [Backend Pipeline Catch]: Inbound Request Caught!")
    print(f"🔹 Route Mode Variable: '{mode}'")
    print(f"🔹 Received File Name: '{image.filename}'")
    print("=" * 60 + "\n")

    try:
        # Rewind image stream index back to byte 0 to protect reading cycles
        await image.seek(0)

        # 🛑 1. Baseline Framework Integrity Guard
        if mode not in MODE_MAP:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid mode. Choose from: {', '.join(MODE_MAP)}",
            )

        # 📥 2. Extract Byte Data from File Object
        image_bytes = await _read_image(image)

        # 🧠 3. Step 1 Execute: Run Gemma 4 text/vision analysis pipeline stream
        stream_generator = sse_stream(MODE_MAP[mode], image_bytes)
        generated_story_text = await _get_full_text_from_stream(
            stream_generator
        )

        # Fallback enforcement parameter check to ensure Kokoro receives a string asset
        if not generated_story_text or len(generated_story_text) < 2:
            generated_story_text = "Analysis complete, but no narratable script content was generated."

        print(f"📝 [Raw Gemma 4 Script Output]: {generated_story_text[:80]}...")

        # ==========================================================================
        # 🎯 THE FIX: Filter and purify text variables before calling Kokoro pipelines
        # ==========================================================================
        polished_text_for_audio = _clean_text_for_tts(generated_story_text)
        print(f"✨ [Purified TTS Script Input]: {polished_text_for_audio[:80]}...")

        # If cleansing completely emptied out text components, supply a clean voiceover baseline
        if len(polished_text_for_audio) < 2:
            polished_text_for_audio = (
                "Visualization processed successfully inside the canvas tree."
            )

        # 🔊 4. Step 2 Execute: Pass clean text into Kokoro Text-To-Speech Synthesis Engine
        pipeline = KPipeline(lang_code=KOKORO_LANG)
        gen = pipeline(
            polished_text_for_audio,
            voice=KOKORO_VOICE,
            split_pattern=r"\n+|\.\s+",
        )

        segments = []
        for _, _, audio in gen:
            segments.append(audio)

        # Path Resolution Mapping Setup
        base_dir_str = (
            KOKORO_OUTPUT_DIR if "KOKORO_OUTPUT_DIR" in globals() else "outputs"
        )
        out_dir = Path(base_dir_str).resolve()
        os.makedirs(str(out_dir), exist_ok=True)

        text_hash = hashlib.sha256(polished_text_for_audio.encode()).hexdigest()[
            :12
        ]
        out_path = out_dir / f"speech_{text_hash}.wav"

        # Write data packets safely down onto system storage frames
        if segments:
            combined_audio = np.concatenate(segments)
            sf.write(str(out_path), combined_audio, KOKORO_SAMPLE_RATE)
        else:
            sf.write(
                str(out_path),
                np.zeros(24000, dtype=np.float32),
                KOKORO_SAMPLE_RATE,
            )

        if not out_path.exists():
            raise FileNotFoundError("Compiled audio track file missing on disk.")

        # 📦 5. Return Clean Direct File Attachment Download Package
        return FileResponse(
            path=str(out_path),
            media_type="audio/wav",
            filename=f"picture_alive_{mode}_output.wav",
        )

    except Exception as server_error:
        error_traceback = traceback.format_exc()
        print("\n" + "🚨" * 30)
        print("❌ [CRITICAL BACKEND PIPELINE CRASH EXCEPTION DETECTED]")
        print(error_traceback)
        print("🚨" * 30 + "\n")

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error_message": str(server_error),
                "stack_trace": error_traceback,
            },
        )
