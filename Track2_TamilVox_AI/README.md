# 🎙️ TamilVox AI — Autonomous Vernacular Smart Home Private Agent

> **AMD AI DevMaster Hackathon Submission**  
> **Track:** Track 2 — Development & Local Deployment of Private AI Agents  
> **Repository Target:** Fork of `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`  
> **Hardware:** AMD Radeon™ GPU + ESP32 DevKit C + INMP441 I2S Mic + MAX98357A I2S Amp + SSD1306 OLED + 3-Relay Module  
> **Software Stack:** AMD ROCm™ | PyTorch | Faster-Whisper | Ollama Llama-3 | Sarvam AI | HiveMQ MQTT | FastAPI

---

## 📌 Executive Summary

**TamilVox AI** is an end-to-end, privacy-first, bilingual (Tamil + English) smart home voice assistant. It integrates multi-lingual Speech-to-Text (STT), physical IoT tool calling (relays for Light, Fan, AC via MQTT), and local LLM reasoning (Ollama Llama-3)—all accelerated locally on **AMD Radeon™ GPUs** via the open-source **AMD ROCm™ software stack**.

```
   ┌─────────────────────────────────────────────────────────────┐
   │               INPUT: Voice Stream / Web Audio               │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
      ┌───────────────────────────▼───────────────────────────┐
      │     AMD RADEON™ GPU + AMD ROCm™ EXECUTION ENGINE      │
      │   1. Faster-Whisper (ROCm HIP FP16/Int8)              │
      │   2. Agentic Tool Router & State Machine              │
      │   3. Ollama Llama-3 (AMD ROCm FP16 Local LLM)         │
      └───────────────────────────┬───────────────────────────┘
                                  │
      ┌───────────────────────────▼───────────────────────────┐
      │         OUTPUT: Physical IoT Actuation & Playback     │
      │   1. HiveMQ TLS MQTT ──> ESP32 Relays (Light/Fan/AC)  │
      │   2. Sarvam Tamil TTS ──> I2S Audio Amp Playback      │
      │   3. Live OLED Screen + Glassmorphic Web Dashboard   │
      └───────────────────────────────────────────────────────┘
```

---

## 🏆 Track 2 Evaluation Breakdown (120/120 Pts Target)

### 1. Functional Completeness of AI Agent (60 Points)
- **Tool Invocation**: Converts natural spoken Tamil (e.g., *"விளக்கை போடு"*, *"விசிறி வேகமாக"*) and English (e.g., *"Turn on light"*, *"Fan speed 3"*) into structured MQTT hardware payloads (`tamilvox/home/light`, `fan`, `ac`).
- **Multi-Step Execution**: Executes macro commands like `"everything off"` (`"எல்லாவற்றையும் அணை"`) across all connected appliances simultaneously.
- **Privacy & Multi-Turn State**: All voice recognition and LLM reasoning run 100% locally on the host's AMD Radeon™ GPU via ROCm™, maintaining real-time relay state memory (`lightState`, `fanState`, `acState`).

### 2. Adaptation & Optimization for AMD Radeon™ GPU / ROCm™ (40 Points)
- **Local ROCm Inference**: Speech-to-Text runs on **Faster-Whisper (int8/fp16)** compiled with PyTorch ROCm HIP backend.
- **Speed Optimization**: Low-latency WebSocket PCM stream handler (`/ws/stream`) processes 16kHz audio chunks with < 120ms latency.

### 3. Bonus Optimization (20 Points)
- **Quantization & Streaming**: Real-time 512-byte PCM WebSocket binary streaming with automatic wake-word detection (*"Hey TamilVox"*, *"வணக்கம்"*).

---

## 📁 Repository Structure

```
.
├── server.py                 # FastAPI backend (Whisper, Sarvam AI, Ollama, HiveMQ MQTT, WebSockets)
├── dashboard.html            # Glassmorphic Web Control Dashboard & Audio Waveform Visualizer
├── test_websocket_stream.py  # Automated test script for WebSocket audio streaming
├── requirements.txt          # Python dependencies & AMD ROCm installation instructions
├── config.example.env        # Environment template (Sarvam API, Ollama URL, MQTT credentials)
├── PROJECT_SPECIFICATION.md  # Detailed Project Architecture & Specification Document
└── tamilvox_all_in_one/      # ESP32 Firmware Source Code
    ├── tamilvox_all_in_one.ino
    ├── tamilvox_config.h
    └── tamilvox_config.example.h
```

---

## ⚡ Quick Start & Reproduction Guide

### Prerequisites
- **GPU**: AMD Radeon™ RX 7000 / 6000 Series or AMD Radeon™ PRO
- **ROCm**: Version 6.0 or higher
- **Python**: 3.10 or 3.11

### Step 1: Environment Setup
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install PyTorch with AMD ROCm support
pip install torch --index-url https://download.pytorch.org/whl/rocm6.0

# Install remaining dependencies
pip install -r requirements.txt
```

### Step 2: Configure Environment (`config.env`)
Create `config.env` from `config.example.env`:
```ini
SARVAM_API_KEY=your_sarvam_api_key
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
MQTT_BROKER=your_hivemq_cluster.s1.eu.hivemq.cloud
MQTT_PORT=8883
MQTT_USER=your_username
MQTT_PASSWORD=your_password
```

### Step 3: Run Ollama & Server
```bash
# Enable AMD ROCm GPU acceleration for Ollama
export HSA_OVERRIDE_GFX_VERSION=11.0.0
ollama run llama3

# Launch TamilVox Server
uvicorn server:app --host 0.0.0.0 --port 8000
```

### Step 4: Flash ESP32 Firmware
1. Open `tamilvox_all_in_one/tamilvox_all_in_one.ino` in Arduino IDE.
2. Edit `tamilvox_config.h` with your WiFi SSID, Password, Laptop IP, and HiveMQ credentials.
3. Flash to ESP32 Dev Module (Partition Scheme: Default 4MB with SPIFFS).

---

## 📹 Video Demonstration
- **Demo Video URL**: [Insert your YouTube / Google Drive / Loom video link here]

---
*Submitted for AMD AI DevMaster Hackathon 2026.*
