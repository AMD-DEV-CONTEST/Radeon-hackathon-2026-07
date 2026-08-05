# 📄 AMD AI DevMaster Hackathon Specification Document
## Project Title: TamilVox AI — Autonomous Vernacular Smart Home Private Agent
**Track:** Track 2 — Development & Local Deployment of Private AI Agents

---

### 1. Target Application & Problem Statement
Commercial smart home assistants (Amazon Alexa, Google Home) rely heavily on proprietary cloud infrastructures, generating latency and privacy concerns, while providing poor performance for regional non-English languages (such as Tamil). **TamilVox AI** addresses these problems by providing an open-source, privacy-first, bilingual smart home voice assistant that runs speech-to-text (STT) and LLM inference locally on **AMD Radeon™ GPUs** via **AMD ROCm™**.

---

### 2. Architecture & Tech Stack

- **Hardware Layer**: ESP32 DevKit C, INMP441 I2S Microphone, MAX98357A I2S Amplifier, 0.96" SSD1306 OLED Display, 3-Channel Relay Module (Light, Fan, AC).
- **Backend & Inference Layer**: Python 3.10, FastAPI, Faster-Whisper (Int8/FP16 CUDA/HIP execution on AMD Radeon GPU), Ollama Llama-3 (AMD ROCm accelerated).
- **IoT & Action Layer**: HiveMQ Cloud MQTT broker with TLS encryption (QoS 1).

---

### 3. Core Agentic Capabilities

1. **Tool Actuation**: Maps Tamil and English voice commands to hardware actions via MQTT.
2. **Multi-Turn State Tracking**: Maintains live relay status synchronizing ESP32, backend server, and Web Dashboard.
3. **Fallback Reasoning**: Automatically routes non-command queries to local Ollama Llama-3 for intelligent conversational responses in Tamil.
4. **Low-Latency Streaming**: Supports WebSocket binary 16kHz PCM audio streaming (`/ws/stream`) with real-time wake-word detection (*"Hey TamilVox"*, *"வணக்கம்"*).

---

### 4. AMD ROCm Adaptation & Optimization
- **PyTorch ROCm HIP Backend**: Dynamically initializes Faster-Whisper using ROCm GPU acceleration when available.
- **Ollama GFX Override**: Configured with `HSA_OVERRIDE_GFX_VERSION=11.0.0` for high-throughput FP16 LLM execution on AMD Radeon GPUs.
