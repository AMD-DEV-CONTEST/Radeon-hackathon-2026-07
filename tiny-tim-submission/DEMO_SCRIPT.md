# Demo Script — Tiny Tim: A Documentary-Style Walkthrough

## Concept

Not "here's my model." A real narrative arc: **Blank slate → Learning → First words → Insight.** The audience watches the actual boundary between learned concepts and fluent language emerge, live.

## Production approach

- **Record desktop and narration separately**, edit together in DaVinci Resolve. Clean audio (good mic, no keyboard/fan noise), ability to cut dead time during epochs, smooth zooms on terminal output.
- **B-roll shot on phone**, 60fps where possible (slow motion holds up even in a 30fps final export). Glass side panel off to cut reflections.
- **Screen recordings separate from phone footage** — training, epochs, GPU utilization, checkpoint save/load, chat demo. Recorded losslessly.
- **Music**: subtle, ambient, cinematic pads/soft synth. Narration stays the focus.
- **Color**: slight contrast lift, cool monitor glow, warm desk lighting. Nothing overdone.

## B-roll shot list

**Hardware**: slow pan across the `RX 9070 XT`, fans spinning, motherboard, RAM, case lighting, AMD logo close-up, fingers typing, terminal reflected in side panel glass.

**Workspace** (filmed at an angle, not screen-recorded — more cinematic): VS Code, Go code, HIP kernels, ROCm, terminal, Tiny Tim training.

**Macro shots**: keyboard, mouse, GPU, coffee, notebook, fans, SSD — small details as transitions.

## Script

### Cold open (0:00–0:10)
Black screen. Keyboard clicks. GPU fan spinning up. Monitor turns on.

> *"Every large language model starts the same way... with random numbers."*

Fade in to terminal.

### Intro
> *"Large language models usually arrive as black boxes."* [pause] *"Tiny Tim didn't."*

Logo. Terminal.

> *"Tiny Tim began with random weights. No pretrained model. No fine-tuning. Everything starts from scratch."*

### Training (live, real, uncut)
Training starts. Epochs rolling.

> *"The entire transformer was written in Go. Matrix multiplication. Attention. Backpropagation. Optimizer. Checkpoint generation. GPU acceleration through AMD HIP and ROCm."*

GPU screenshot, fans spinning, GPU working.

> *"As training progresses, loss falls, and Tiny Tim begins organizing knowledge."*

### First words
Checkpoint saves. Chat loads.

Prompt: `AMD makes`

Tiny Tim answers. **Leave it. Don't edit. Let the audience read it — don't cut immediately.**

> *"At first glance... that doesn't look right."*

Highlight: `AMD`, `architecture`, `founded`.

> *"But look closer. Those aren't random words. They're some of the strongest concepts in the training corpus."*

Show corpus.

> *"Tiny Tim has learned that these ideas belong together. What he hasn't fully learned yet is how to express them fluently."*

### The insight (the "watching learning happen" segment)
> *"This is the magic moment. Large language models usually hide this process — they're already trained. Tiny Tim is intentionally small enough that we can actually watch learning happen."* [pause] *"We can see the moment where knowledge begins to emerge, before language has completely caught up."*

**Real, genuine framing worth keeping precise:** learning that concepts belong together is not the same as learning to express them fluently. Even a very small transformer can begin organizing related ideas into meaningful internal representations. Producing natural, grammatically correct language is a more demanding task, generally benefiting from greater model capacity, more diverse data, and longer training. In larger pretrained models, this transition already happened long before anyone interacts with them. Here, it's visible.

### Show the real work
Go code. HIP code. Training. Terminal. GPU.

> *"Every stage is visible. Every tensor. Every weight. Every prediction."*

### Close
Terminal. Cursor blinking.

> *"Tiny Tim isn't impressive because he's large."* [pause] *"He's impressive because every stage of learning is visible."*

Slow pan across the PC. GPU fans slowing. Terminal still open. Fade to black.

> **Tiny Tim**
> *A Go-native transformer trained from scratch using AMD ROCm.*

AMD logo. Done.

## Still to finalize
- Real `benchmark` CLI segment (real ROCm/HIP performance numbers) — where does this fit in the arc?
- Exact real prompts beyond `AMD makes` — confirm each produces a genuinely usable, honest completion before filming
- Runtime check against the real `3–5` minute limit once B-roll/narration pacing is factored in

---

## PPT Outline (10–12 slides, optional supplementary material)

Minimal text. Lots of screenshots. No paragraphs.

**Slide 1 — Title**
> Tiny Tim
> *A Go-native Transformer Trained from Scratch using AMD ROCm*

Name, hackathon, your name.

**Slide 2 — Goal** (one sentence)
> Demonstrate training and inference of a transformer written in Go and accelerated using AMD GPUs through HIP and ROCm.

**Slide 3 — Architecture** (clean diagram)
```
Training Corpus
      ↓
  Tokenizer
      ↓
  Embeddings
      ↓
 Transformer
      ↓
   Output
```

**Slide 4 — Training**
Real screenshot: epochs, loss dropping. Epoch 1 → Epoch 100.

**Slide 5 — GPU**
Real screenshot: ROCm, HIP, GPU utilization, VRAM, temperature.

**Slide 6 — Checkpoint**
Real screenshot: `Saving checkpoint... Done.`

**Slide 7 — Inference**
Real screenshot: `AMD makes` → `architecture...`

**Slide 8 — Learning** (big quote)
> Tiny Tim is intentionally small enough that we can actually watch learning happen.

**Slide 9 — What We Learned**
- Go can train transformers
- HIP accelerates tensor operations
- AMD GPUs provide end-to-end acceleration
- Small models reveal learning in ways larger models cannot

**Slide 10 — Future**
- Larger models
- Better corpora
- More layers
- Better tokenizer

That's it. Simple.