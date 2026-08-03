# 3–5 Minute Demo Runbook

## Goal

Demonstrate that YIJIAN is an evidence-grounded agent running on AMD Radeon, not a prewritten chatbot.

## 0:00–0:25 — Problem

- Show a Go position with the played move and KataGo's preferred move.
- State the failure mode: an ordinary LLM may confuse the two moves or invent the wrong board region.

## 0:25–1:10 — Whole-game review

- Import an SGF.
- Start the full-game analysis.
- Show 32-visit scan progress and the ranked critical-node list.
- Briefly show the Radeon W7900 process monitor or runtime log.

## 1:10–2:10 — Evidence-grounded explanation

- Open a critical node.
- Point out the played move, AI move, win-rate/score change and recommendation marker.
- Ask “Why is this move bad?”
- Show the response and its KataGo evidence footer.

## 2:10–2:55 — Follow-up and self-correction

- Switch the question subject from the played move to the AI move.
- Ask a follow-up about thickness, territory, initiative or local fighting.
- Demonstrate the recommended variation on the board.
- Explain that the answer validator rejects subject, coordinate and region contradictions.

## 2:55–3:30 — Radeon performance

- Show the benchmark summary:
  - 33 positions × 32 visits: 13.55 s.
  - 128-visit verification: 2.63 s.
  - coach evaluation P95: 9.536 s.
- Show Qwen3.6-27B served locally through `llama.cpp` on ROCm 7.2.1.

## 3:30–4:00 — Close

- Show cached reopening from SQLite.
- End with: “Every superhuman move, made understandable.”

## Recording checklist

- English captions or English narration.
- Radeon GPU and runtime identity visible at least once.
- Real user interaction; no purely prerecorded answer cards.
- No API keys, SSH hosts, private SGFs, creator transcripts or personal data visible.
- Export at 1080p if possible.
