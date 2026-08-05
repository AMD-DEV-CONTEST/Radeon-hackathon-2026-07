> **📜 Hackathon submission** — This document was created for the AMD Radeon Hackathon 2026-07 and reflects the project state at that time (August 2026). All figures are validated measurements from `site/benchmarks.json` / `benchmarks/` — see the [README](../README.md) and [current benchmarks](../docs/wiki/performance.md) for up-to-date data.
>
# Demo Video Script — 1bit.systems
## AMD AI DevMaster Hackathon — Track 2 Submission

**Target duration**: 4 minutes

---

### Scene 1: Hardware & Setup (0:00–0:30)

**Visual**: Show the AMD Strix Halo laptop (GMKtec EVO-X2 or similar).
Show `rocm-smi` output listing the Radeon 8060S GPU.
Show `xrt-smi examine` listing XDNA 2 NPU tiles.

**Narration**:
> "This is AMD Strix Halo — Ryzen AI Max+ 395 with a Radeon 8060S GPU, 32 XDNA 2 NPU tiles, and 128 gigabytes of unified memory. We've built an inference engine that uses ALL of this hardware at once — and it's one 400-kilobyte binary."

### Scene 2: One-Command Startup (0:30–1:00)

**Visual**: Terminal window. Type:
```bash
./build/unified_server --port 8088
```
Show server auto-detecting 3 backends (HIP GPU, XDNA2 NPU, CPU fallback).
Show the health endpoint: `curl localhost:8088/v1/health` returning JSON with all backends.

**Narration**:
> "One command. No config files. No Python. No Docker. The server auto-detects the hardware, discovers available models, and starts serving. Let's see what backends it found."

### Scene 3: Model Demo — Voice-to-Voice (1:00–1:45)

**Visual**: Phone running 1bit Mobile. Tap the microphone button. Speak: "What's the weather like today and should I bring an umbrella?" Show the phone screen with transcribed text, then the agent's response.
Show the server log on the laptop side, highlighting token throughput (tok/s) as tokens stream.

**Narration**:
> "Here's Jarvis — our local AI agent. I just asked it a question using 1bit Mobile on my phone. The audio goes to Whisper for transcription, the text goes to our unified server running BlackMamba on the GPU, and the response comes back as synthesized speech — all on-device. No cloud. No API keys."

### Scene 4: Multi-Backend Routing (1:45–2:15)

**Visual**: Split screen. Left: `nvtop` showing GPU utilization. Right: server log showing backend switches.
Send a request with `X-Backend: cascade` header.
Show token routing log — tokens dispatched to GPU, then NPU, then GPU again.

**Narration**:
> "The Token Router dispatches each token to the fastest available backend. Watch — this request starts on the GPU for attention computation, then the router switches to the NPU for the feedforward layers, and back to GPU. All invisible to the client. If a backend fails, the server auto-cascades to the next one."

### Scene 5: Performance Numbers (2:15–2:45)

**Visual**: Terminal showing benchmark runs:
```
Benchmark: Q1 GEMV (GPU 1-bit) — 433 tok/s
Benchmark: Fused TQ2 (GPU ternary) — 420 tok/s
Benchmark: Qwen3.6-35B-A3B NPU (XDNA 2, FLM) — 11.66 tok/s
Benchmark: BlackMamba 1.5B (Mamba1 HIP) — 79.4 tok/s
```

Show a comparison chart or table.

**Narration**:
> "Performance. Our fused Q1 GEMV kernel hits 433 tokens per second on the Radeon GPU. The XDNA 2 NPU drives a 35-billion-parameter Qwen model at 11.66 tokens per second — with prefill 8 to 24 percent faster than AMD's own published numbers. BlackMamba 1.5B runs at nearly 80 tok/s on the GPU. All on a laptop."

### Scene 6: Private Agent Capabilities (2:45–3:15)

**Visual**: Demonstrate Jarvis with tools:
1. "Summarize this PDF" → agent calls file tool, reads PDF, returns summary
2. "Run my test suite and tell me what failed" → agent calls shell tool, runs `ctest`, reports failures
3. Show the permission gate pop-up for risky operations

**Narration**:
> "Jarvis isn't just a chatbot. It has tools — it can read files, run code, fetch web pages. But every risky operation goes through a permission gate. You control what your agent can do. And because everything runs on-device, your data never leaves this machine."

### Scene 7: Innovation Recap (3:15–3:45)

**Visual**: Quick montage of:
- The reverse-engineering journey: AMD NPU decompiled
- The 1BP format: 256-byte header animation
- The architecture diagram
- The GitHub repo: 1,322 source files, MIT license

**Narration**:
> "What we built: We reverse-engineered AMD's NPU in 4 days with no documentation. We created the 1BP format — one file, zero config. We built a token router that dispatches across GPU, NPU, and CPU. And we made it all open source under the MIT license — one binary, all backends, zero Python."

### Scene 8: Call to Action (3:45–4:00)

**Visual**: GitHub repo URL on screen.
```
github.com/1bit-systems/1bit-systems
1bit.systems
```

**Narration**:
> "One binary to rule them all. Check out the repo at github.com/1bit-systems/1bit-systems. Try it on your Strix Halo. Thank you."

---

### Recording Tips
- Record at 1080p, 30fps
- Use OBS Studio with window capture for terminal
- Record phone screen via `scrcpy` for mobile demo
- Keep terminal font large (16pt+)
- Show `nvtop` or `rocm-smi` in a corner for GPU utilization proof
- Audio: use a good microphone, record narration separately
