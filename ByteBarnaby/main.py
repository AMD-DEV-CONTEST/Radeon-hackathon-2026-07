import os
import io
import zipfile
import json
import uuid
from omnivoice import OmniVoice
from fastapi import FastAPI, Form
from fastapi.staticfiles import StaticFiles

import torch
from openai import OpenAI
from prompts import get_system_prompt
from news import get_news
from transformers import Wav2Vec2Processor, Wav2Vec2ForCTC
from forced_alignment import forced_align
from fastapi.responses import Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Allowing everything as it is a local app.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],
)

EPISODES_DIR = "./episodes"
os.makedirs(EPISODES_DIR, exist_ok=True)
app.mount("/episodes", StaticFiles(directory=EPISODES_DIR), name="episodes")

BUILD_DIR = "./Build"

app.mount("/TemplateData", StaticFiles(directory=os.path.join(BUILD_DIR, "TemplateData")), name="template_data")

@app.get("/Build/{filename}")
async def serve_unity_build(filename: str):
    filepath = os.path.join(BUILD_DIR, "Build", filename)

    if not os.path.exists(filepath):
        return Response(status_code=404, content="File not found")

    with open(filepath, "rb") as f:
        content = f.read()

    headers = {}

    if ".wasm" in filename:
        media_type = "application/wasm"
    elif ".js" in filename:
        media_type = "application/javascript"
    else:
        media_type = "application/octet-stream"
    
    # Inject brotli header
    if filename.endswith(".br"):
        headers["Content-Encoding"] = "br"
    
    return Response(content=content, media_type=media_type, headers=headers)

@app.get("/")
async def homepage():
    return FileResponse(os.path.join(BUILD_DIR, "index.html"))


def create_episode_zip(episode_payload, audio_chunks):
    """
    Args:
        episode_payload: Json containing the dialogues
        audio_chunks: dict containing file names mapped to np.float32 arrays
    """
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        zip_file.writestr("episode.json", json.dumps(episode_payload))
        for filename, audio_array in audio_chunks.items():
            zip_file.writestr(filename, audio_array.tobytes())
    
    return zip_buffer.getvalue()

align_processor = Wav2Vec2Processor.from_pretrained("./wav2vec2_model")
align_model = Wav2Vec2ForCTC.from_pretrained("./wav2vec2_model", dtype=torch.float16).to("cuda:0")

model = OmniVoice.from_pretrained(
    "./omnivoice_model", device_map="cuda:0", dtype=torch.float16
)

TTS_SAMPLE_RATE = 24000

client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="llama.cpp")

@app.post("/generate")
def generate_news(keyword: str = Form(...)):
    headlines, news = get_news(keyword)
    response = client.chat.completions.create(
        model="default",
        messages=[
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": news},
        ],
        reasoning_effort="none",
    )

    raw_json_string = response.choices[0].message.content

    news_script = json.loads(raw_json_string)
    news_script["headlines"] = headlines
    print(news_script["dialogues"])

    print("Generating audio...")

    all_audio = {}

    for i, item in enumerate(news_script.get("dialogues", [])):
        dialogue = item["dialogue"]
        expression = item["expression"]
        print(f"Synthesizing [{expression}]: {dialogue}")

        audio_output = model.generate(
            text=dialogue,
            ref_audio="mike.wav",
            ref_text="I like horror stories, like a lot, and also romantic comedy.",
        )  # audio is a list of `np.ndarray` with shape (T,) at 24 kHz.

        audio_chunk = audio_output[0].squeeze()
        audio_file_name = f"dialogue_{i}.bin"
        news_script["dialogues"][i]["audioFileName"] = audio_file_name
        all_audio[audio_file_name] = audio_chunk

        align_result = forced_align(align_model, align_processor, audio_chunk, TTS_SAMPLE_RATE, dialogue)
        visemes = align_result["visemes"]

        news_script["dialogues"][i]["visemes"] = visemes

    zip_bytes = create_episode_zip(news_script, all_audio)
    unique_id = uuid.uuid4().hex[:8]
    filename = f"episode_{unique_id}.zip"

    with open(os.path.join(EPISODES_DIR, filename), "wb") as f:
        f.write(zip_bytes)
        print(f"Successfully saved locally: {filename}!")

    return filename

