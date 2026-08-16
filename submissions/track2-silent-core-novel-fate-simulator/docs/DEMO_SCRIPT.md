# Hello E World — Demo Video Script (3:30)

**Format**: Word-for-word English narration + on-screen actions
**Use**: Read aloud for voiceover, or use as subtitles directly
**Tone**: Calm, thoughtful, confident. Not salesy. Like explaining something to a smart friend.

---

## Scene 1: Hook (0:00 – 0:25)

**Screen**: Black background. Three lines of text fade in sequentially:

> "What if you had said yes instead of no?"

> "What if you had stayed instead of left?"

> "What if you could see every version of yourself?"

**Fade to**: Browser window. Hello E World UI loads — dark theme, purple accent, sidebar with "AMD Radeon W7900 · llama.cpp" badge pulsing green.

**Narration**:

> Every decision we make closes some doors and opens others.
> But we never get to see what was behind the doors we closed.
> Until now.

---

## Scene 2: The Conversation (0:25 – 1:20)

**Screen**: The chat UI is open. AI sends its first message:

> "Hi. I'm not a form, and I'm not a chatbot. I'm here to understand how you think — so I can show you the versions of yourself that different choices would create."

Click the **"⚡ Demo"** button in the sidebar. 6 Q&A pairs appear instantly — showing a natural conversation flow:

- AI: "What's a decision that changed everything?"
- User: "Leaving my corporate job at 28 to start a company..."
- AI: "How did you make that decision?"
- User: "I made a spreadsheet at first... but honestly the real decision was emotional..."

**Narration**:

> This is Hello E World. No forms, no questionnaires.
> It talks to you — one question at a time — and follows up on what you say.
> In five minutes, it understands how you think.
> Click Demo to preload a sample conversation and skip ahead.

---

## Scene 3: Personality Extraction (1:20 – 1:55)

**Screen**: Click **"🔮 Extract My Personality"**. A typing animation plays: "Analyzing your answers, building your personality model..."

Then the profile appears:

> **Risk style**: High
> **Decision style**: Intuitive
> **Values**: Freedom, Impact, Connection, Growth, Autonomy
> **Strengths**: Pattern recognition, empathy, resilience
> **Blind spots**: Avoids conflict, holds grudges
>
> *You are someone who trusts their gut over data, sees patterns others miss, but struggles to let go of perceived slights...*

**Narration**:

> What you're seeing is not a guess.
> It's a sixteen-dimension personality model — extracted from your own words.
> Risk tolerance. Decision style. Cognitive biases. Blind spots.
> All built entirely on this AMD Radeon GPU. No data leaves this machine.

---

## Scene 4: What-If Simulation (1:55 – 3:00)

**Screen**: The input bar changes to a what-if prompt. Type:

> "What if I started a company at 25 instead of waiting until 30?"

Click **🔮 Simulate**. Typing animation: "Simulating parallel universes on AMD Radeon GPU..."

The report renders in the chat — three color-coded paths:

**Path A: Most Likely** (blue left border)
> "You start with the same cautious approach, but five years earlier. By 30, you've had one failed venture, learned faster, and your second company has product-market fit. You're more confident but also more scarred."

**Path B: Optimal** (green left border)
> "The early start compounds. You meet the right co-founder at 26. By 30, you've raised a seed round. Five extra years of entrepreneurial experience puts you three years ahead of where you actually are."

**Path C: Shadow** (red left border)
> "Without the corporate experience to fall back on, your first failure hits harder. You burn savings, isolate yourself, and the imposter syndrome you already have gets louder. You spend two years in a spiral before recovering."

Scroll down to show:

> **Bias Analysis**: Your overconfidence in pattern recognition makes you underestimate the role of luck...
>
> **Closing Insight**: "You're not deciding between starting at 25 vs 30. You're deciding whether to trust yourself before you feel ready. You will never feel ready."

**Narration**:

> Three parallel paths. Not fortune-telling — simulation.
> Based on who you actually are. Your risk tolerance. Your blind spots. Your strengths.
> Path A: what would probably happen. Path B: if everything broke your way. Path C: if your weaknesses ran the show.
> Every path feels true — because it IS true to you.
> And the closing insight doesn't tell you what to do. It shows you what you're really deciding.

---

## Scene 5: Tech Proof & Close (3:00 – 3:30)

**Screen**: Switch to terminal window. Run:

```bash
rocm-smi
```

Show GPU output: AMD Radeon Pro W7900, 48GB VRAM, utilization spiking during inference.

Switch back to the Hello E World UI.

**Narration**:

> Running entirely on AMD Radeon Pro W7900. Forty-eight gigabytes of VRAM.
> llama.cpp serving Qwen 2.5 14B Instruct — forty-five tokens per second.
> No API calls. No cloud. Your personality data never leaves this machine.

**End screen** (black, centered text):

> **Hello E World**
> See every version of yourself.
>
> Track 2 — Private AI Agent — Local Deployment
> github.com/west-liu/Radeon-hackathon-2026-07

**Narration**:

> Hello E World. See every version of yourself.

---

## Recording Checklist

**Before recording**:
- [ ] Clear browser cache, load Hello E World fresh
- [ ] Open terminal, ready to run `rocm-smi`
- [ ] OBS Studio configured: 1920x1080, 30fps

**Recording steps**:
1. Start recording
2. Scene 1: show the three hook lines (use the HTML or pre-type in a text editor)
3. Scene 2-4: switch to browser, click Demo, follow the flow
4. Scene 5: switch to terminal, run `rocm-smi`, switch back
5. Stop recording

**Voiceover**:
- Record separately for clean audio (recommended)
- Or record live while demoing
- English is required per hackathon rules
- Total target: 3:00–3:30

**Subtitle file**: The narration blocks above can be used directly as .srt subtitle entries with timing adjustments.
