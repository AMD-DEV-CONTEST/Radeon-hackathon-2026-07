# NodeFlow Demo Video — Requirements & Script

> For AMD AI DevMaster Hackathon 2026 Track 1 Submission
> Duration: 3–5 minutes | Language: English (or Chinese with English subtitles)

---

## 1. Technical Specs

| Item | Requirement |
|------|-------------|
| Duration | 3–5 minutes (aim for 3.5–4 min) |
| Resolution | 1080p (1920×1080), landscape |
| Frame Rate | 30fps |
| Format | MP4 (H.264) |
| Audio | Clear English voiceover (or Chinese with English subtitles) |
| File Size | Under 500MB |

## 2. What Judges Will Evaluate

Based on official rules, the demo video must demonstrate:

1. **Actual operation process** — not a slideshow, real clicking and generating
2. **Real AMD Radeon GPU execution** — show GPU name, ROCm runtime, VRAM usage somewhere in the video
3. **Performance on AMD Radeon GPU** — from input to final result, show the actual time
4. **Output quality** — clarity, stability, and diversity of generated images

## 3. Recording Setup

### Screen Recording Tools
- **OBS Studio** (free, recommended): https://obsproject.com
- **Screen recording**: 1920×1080, 30fps, capture browser window
- **Audio**: Use a decent microphone, record voiceover separately if needed

### Before Recording
1. Pre-load models on the GPU instance (start backend, wait for model to load)
2. Clear browser cache, refresh the page
3. Close unnecessary tabs/apps
4. Have your sketch ready (pre-draw a simple character or scene)
5. Test screen + audio recording with a 10-second clip first

### Browser Setup
- Open NodeFlow in Chrome/Edge fullscreen (F11)
- Zoom level: 100% (Ctrl+0)
- Make sure the public URL works before recording

## 4. Video Script (Scene by Scene)

### Scene 1: Opening (0:00 – 0:20)

**Visual:**
- NodeFlow interface loaded, with the title/logo visible
- Text overlay: "NodeFlow — Infinite Canvas AI Stylization Workstation"
- Text overlay: "Running on AMD Radeon PRO W7900 · ROCm Native"

**Voiceover:**
> "This is NodeFlow, an AI image generation workstation running natively on AMD Radeon GPUs. It combines infinite canvas sketching with diffusion model generation — no NVIDIA CUDA dependency."

**Action:** Hold on the interface for 3 seconds, then start.

---

### Scene 2: GPU Proof (0:20 – 0:35)

**Visual:**
- Open a new browser tab, navigate to `https://your-url/api/health`
- Or show terminal: `rocm-smi --showproductname` + `python3 -c "import torch; print(torch.cuda.get_device_name(0))"`

**Voiceover:**
> "The entire inference pipeline runs on an AMD Radeon PRO W7900 with 48 gigabytes of VRAM, using the ROCm runtime and PyTorch ROCm wheels."

**Action:** Show the JSON response or terminal output confirming GPU model.

---

### Scene 3: Sketch-to-Art Demo (0:35 – 1:30)

**Visual:**
- Back to NodeFlow canvas
- Draw a simple sketch on the Excalidraw canvas (a character outline, a tree, a building — something recognizable)
- Select "Sketch → Art" mode
- Choose a style: **Watercolor**
- Set strength slider to 0.8
- Click **Generate**
- Show the loading state (button shows "Generating...")
- Wait for result (~3-5 seconds for Fast mode)
- Show the generated image appearing in the result panel

**Voiceover:**
> "In Sketch-to-Art mode, I draw directly on the infinite canvas. I select Watercolor style with 0.8 strength, and click Generate. The canvas is exported as a PNG and sent to the backend, where the diffusion model transforms my sketch into a finished watercolor painting — in just a few seconds."

**Key timing note:** Show the actual wait time. Don't cut it — judges want to see real performance.

---

### Scene 4: Style Switching (1:30 – 2:15)

**Visual:**
- With the same sketch still on canvas, switch style to **Cyberpunk**
- Click Generate again
- Show result
- Switch to **3D Render**
- Click Generate
- Show result
- Place the 3 results side by side (or switch between them)

**Voiceover:**
> "Same sketch, different styles. Cyberpunk adds neon and futuristic elements. 3D Render gives it a photorealistic, cinematic look. One sketch, three completely different interpretations — all generated on the same AMD GPU."

---

### Scene 5: Text-to-Art Demo (2:15 – 2:50)

**Visual:**
- Switch to "Text → Art" mode (top toolbar)
- Type a prompt: "a serene mountain lake at dawn with mist rising from the water"
- Select style: **Oil Painting**
- Click Generate
- Show the result

**Voiceover:**
> "NodeFlow also supports text-to-image generation. I type a description, select Oil Painting style, and the backend appends a professional prompt prefix before generating. The result is an oil-painting-style landscape."

---

### Scene 6: Dual-Mode Speed Comparison (2:50 – 3:30)

**Visual:**
- Switch to Fast mode (if not already)
- Generate an image — show it takes ~2-3 seconds
- Switch to Expert mode
- Generate the same prompt — show it takes ~12-20 seconds
- Show the quality difference (Expert mode should look better)

**Voiceover:**
> "NodeFlow has two modes. Fast mode uses SDXL-Lightning, a 4-step distilled model — generation takes about 2 seconds. Expert mode uses full models like NoobAI XL or FLUX.2-klein with 28 to 50 steps — it takes longer but produces higher quality results with full parameter control."

---

### Scene 7: Multi-Model + LoRA (3:30 – 4:10)

**Visual:**
- Open model selection panel
- Show switching from SDXL-Lightning to NoobAI XL (or another model)
- Open LoRA panel
- Adjust a LoRA weight slider
- Generate with the new model + LoRA

**Voiceover:**
> "Models can be hot-switched without restarting the service. I switch from SDXL-Lightning to NoobAI XL for anime-style output. LoRA weights are adjustable in real time — I can mix a realistic base with an anime LoRA to create hybrid styles. The system automatically reduces LoRA weights for distilled models to prevent artifacts."

---

### Scene 8: Closing (4:10 – 4:30)

**Visual:**
- Return to the main interface
- Text overlay: "NodeFlow"
- Text overlay: "AMD Radeon PRO W7900 · 48GB VRAM · ROCm 7.x · PyTorch 2.x"
- Text overlay: "Track 1, Chen Jianghao, NodeFlow"

**Voiceover:**
> "NodeFlow proves that a full-featured AI image generation tool — with canvas interaction, multi-model support, and LoRA integration — can run entirely on AMD Radeon hardware via ROCm. No CUDA, no compromises. Thank you."

---

## 5. Post-Production Tips

### Subtitles
- If recording in Chinese: add English subtitles (required by rules)
- Use a clean sans-serif font (Arial, Helvetica)
- Subtitle position: bottom center, with dark background bar for readability

### Text Overlays
- Use for: GPU name, model names, timing, style names
- Keep on screen for at least 2 seconds
- Font: clean sans-serif, white text with subtle shadow

### Cuts & Transitions
- Keep cuts simple (hard cuts or 0.3s crossfade)
- Don't over-edit — judges want to see real performance, not a music video
- Show actual generation wait times (don't fast-forward through loading)

### Background Music
- Optional, very low volume (10-15% of voiceover)
- Instrumental, no vocals
- Something subtle and tech/ambient

## 6. Checklist Before Finalizing

- [ ] Video is 3–5 minutes long
- [ ] Shows AMD Radeon GPU name (W7900) somewhere
- [ ] Shows ROCm / PyTorch info
- [ ] Demonstrates Sketch-to-Art (img2img)
- [ ] Demonstrates Text-to-Art (text2img)
- [ ] Shows actual generation time (not edited out)
- [ ] Shows multiple styles on same sketch
- [ ] Shows Fast vs Expert mode difference
- [ ] Shows model switching
- [ ] Voiceover is clear and in English (or has English subtitles)
- [ ] Resolution is 1080p
- [ ] File is MP4 format
- [ ] File size under 500MB

## 7. Quick Reference: Prompt Ideas for Demo

| Scene | Prompt | Style |
|-------|--------|-------|
| Sketch 1 | (hand-drawn character/tree/building) | Watercolor |
| Sketch 1 repeat | (same sketch) | Cyberpunk |
| Sketch 1 repeat | (same sketch) | 3D Render |
| Text 1 | "a serene mountain lake at dawn with mist rising from the water" | Oil Painting |
| Text 2 (Expert) | "a futuristic samurai standing in a neon-lit alley" | Concept Art |

---

*This document is for internal use. The final video should be uploaded and linked in the PR description.*
