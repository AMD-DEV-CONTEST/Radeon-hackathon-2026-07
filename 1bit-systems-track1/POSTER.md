# 1bit Studio — Track 1 Poster

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║                    1bit.systems · 1bit Studio                ║
║           Image & Video Generation — One C++ Binary          ║
║                                                              ║
║   AMD Radeon Hackathon 2026-07 · Track 1 · MIT · Zero Python ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║  WHAT IT IS                                                   ║
║  • OpenAI-compatible image & video generation server          ║
║  • SD / SDXL / FLUX / Qwen-Image / Z-Image  (+ LoRA)          ║
║  • Wan2.1 / LTX / Hunyuan text-to-video, WebM/AVI encode      ║
║  • ComfyUI nodes: 1BP Image Generate · 1BP Video Generate     ║
║  • Runs inside the same binary as the LLM/VLM/TTS engine      ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║  MEASURED (Radeon 8060S, ROCm, Strix Halo)                    ║
║  • SD1.5 txt2img 512×512, 20 steps ......... ~10.8 s          ║
║  • Wan2.1 T2V 1.3B ........ 2m38s ROCm vs 8m48s CPU (3.3×)    ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║  WHY AMD                                                  ║
║  • Pure C++ — no torch+ROCm wheel pairing, no venv, no forks  ║
║  • Backend-agnostic: ROCm / Vulkan / CUDA / Metal / CPU       ║
║  • Fully on-device — your content never leaves your machine   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

**Source**: https://github.com/1bit-systems/1bit-systems · **Demo**: `demo_track1.mp4`
