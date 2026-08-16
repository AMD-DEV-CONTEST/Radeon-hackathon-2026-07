# Hello E World Demo Video Script (3:30)

**Narrator**: Calm, thoughtful. Not salesy.

---

## Scene 1: The Hook (0:00-0:30)

**Screen**: Black background. Text fades in:
> "What if you had said yes instead of no?"

Text changes:
> "What if you had stayed instead of left?"

Text changes:
> "What if you could see every version of yourself?"

**Fade to**: Browser window opens. Hello E World UI loads. Purple accent on dark theme.

**Narration**:
"Every decision we make closes some doors and opens others. But we never get to see what was behind the doors we closed. Until now."

---

## Scene 2: The Conversation (0:30-1:30)

**Screen**: Click "⚡ Demo" button. 6 Q&A pairs appear instantly.

Show the chat flowing:
- AI: "What's a decision that changed everything?"
- User answer pre-filled
- AI: "How did you make that decision?"
- User answer
- AI: "What are you most afraid of right now?"

**Narration**:
"No forms. No questionnaires. Hello E World talks to you — one question at a time. It follows up on what you say, goes deeper when you're ready. In 5 minutes, it understands how you think."

**Click**: "🔮 Extract My Personality"

Profile appears:
```
Risk Style: High
Decision Style: Intuitive
Values: Freedom, Impact, Connection
Strengths: Pattern recognition, empathy
Blind Spots: Avoids conflict, holds grudges
```

**Narration**:
"What you're seeing isn't a guess. It's a personality model extracted from your own words — 16 dimensions, built entirely on this AMD Radeon GPU. No data leaves this machine."

---

## Scene 3: The Simulation (1:30-2:45)

**Screen**: What-if input bar appears. Type:
> "What if I started a company at 25 instead of waiting until 30?"

Click "🔮 Simulate". Show the report rendering:

**Path A: Most Likely** (blue)
"You start with the same cautious approach, but 5 years earlier. By 30, you've had one failed venture, learned faster, and your second company has product-market fit. You're more confident but also more scarred. Emotion: Grounded optimism with hard-won edges."

**Path B: Optimal** (green)  
"The early start compounds. You meet the right co-founder at 26. By 30, you've raised a seed round. The extra 5 years of entrepreneurial experience puts you 3 years ahead of where you actually are. Emotion: Fulfilled, slightly overwhelmed, but aligned."

**Path C: Shadow** (red)
"Without the corporate experience to fall back on, your first failure hits harder. You burn savings, isolate yourself, and the imposter syndrome you already have gets louder. You spend 2 years in a spiral before recovering. Emotion: Regret mixed with resilience earned the hard way."

**Narration**:
"Three parallel paths. Not fortune-telling — simulation. Based on who you actually are. Your risk tolerance. Your blind spots. Your strengths. Every path feels true because it IS true — to you."

---

## Scene 4: The Insight (2:45-3:15)

**Screen**: Scroll to Bias Analysis and Closing Insight:

> "Bias Analysis: Your overconfidence in pattern recognition makes you underestimate the role of luck. You attribute the 'optimal' path to skill, but the gap between Path A and B is mostly timing — something you cannot fully control."
>
> "Closing Insight: You're not deciding between starting at 25 vs 30. You're deciding whether to trust yourself before you feel ready. You will never feel ready."

**Narration**:
"Hello E World doesn't tell you what to do. It shows you who you are — and lets you see the versions of yourself that different choices create. Sometimes the best advice isn't advice. It's a mirror."

---

## Scene 5: Tech & Close (3:15-3:30)

**Screen**: Show terminal with `rocm-smi` output, then back to UI.

**Narration**:
"Running entirely on AMD Radeon Pro W7900. llama.cpp. 45 tokens per second. Your personality data never leaves this machine. Hello E World. See every version of yourself."

**End screen**: 
```
Hello E World
Track 2 - Private AI Agent - Local Deployment
github.com/west-liu/Radeon-hackathon-2026-07
```

---

## Recording Instructions

### What you need:
1. Screen recorder (OBS Studio recommended)
2. Browser open to Hello E World UI
3. Another terminal window showing `rocm-smi`

### Steps to record:
1. Clear browser cache, open Hello E World
2. Start OBS recording
3. Click Demo, follow the script
4. For Scene 5: switch to terminal, run `rocm-smi`, show GPU stats
5. Stop recording

### Narration:
- Record voiceover separately (cleaner audio)
- Or record live while demoing
- English is required per hackathon rules

### Total time: ~3:30
- Can trim to exactly 3:00 or extend to 5:00
