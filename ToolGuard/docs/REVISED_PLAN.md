# ToolGuard — Revised 6-Day Plan (July 31 → Aug 6, 2026)

Original code was lost when the Radeon Cloud instance was wiped
(server issue + no local/git backup). Restarting from zero with 6
days left instead of 17. Scope has been cut to fit — see below.

## Scope cut (locked in — do not add back without a team discussion)

Target **3 failure patterns**, not 4-5:
1. Plain text instead of structured tool call
2. Wrong/malformed tool name
3. Schema leak instead of a real result

Dropped: "dropped streamed tool call" — hardest to reliably reproduce
and fix, cutting it buys a full extra day. Can revisit ONLY if Day 3
finishes early and clean.

Dashboard: simple live log/table of tool calls + pass/fail, not a
polished UI. Function over form.

## Day-by-day

**Day 1 — Jul 31 (today)**
- Push this repo to GitHub. Confirm everyone can clone + push.
- Relaunch Radeon Cloud instance, re-run setup_env.sh, get vLLM
  serving again (commands already known from before, should be hours).
- Team confirms the scope cut above.

**Day 2 — Aug 1**
- Person A: fake tool agent (LangGraph) + trigger patterns 1 & 2 on demand.
- Person B: detection logic for patterns 1 & 2.
- Person C: confirm vLLM stable, start dashboard skeleton.

**Day 3 — Aug 2**
- Person A: trigger pattern 3 + write down exact repro steps for all 3.
- Person B: auto-fix/retry logic for all 3 patterns.
- Person C: dashboard shows live tool-calls as they happen.

**Day 4 — Aug 3 — Integration day (everyone)**
- Connect Person A + B + C into one pipeline. Expect bugs.
  Budget the entire day for this, no other work.

**Day 5 — Aug 4**
- Run the full demo 5+ times, fix whatever breaks, time it (aim <3 min).
- Run real benchmark: failure rate with ToolGuard OFF vs ON, many runs,
  real numbers.
- Write the Project Specification Document + finish README
  (include ROCm/vLLM config + any optimization notes — required for
  the 40% GPU-optimization score).

**Day 6 — Aug 5**
- Record the demo video (3-5 min).
- Build the PPT/poster.
- Fork the official repo, open the PR titled
  "Track 2, <team name>, <app name>".
- **Submit today, not Aug 6.** Don't sit on it.

**Aug 6 — pure emergency buffer**
Only touch this if something breaks after submission, or to fix
something a reviewer flags. No new features.

## Rules that got us here — keep them this time
1. Commit and push to GitHub after every real chunk of work. Every day,
   multiple times a day. This is the #1 thing that would have prevented
   this whole restart.
2. If Day 2 goes badly, cut to 2 patterns immediately — don't try to
   catch up by rushing pattern 3.
3. Don't skip the daily standup, even for 5 minutes over voice/text.
4. Submit the PR as soon as Day 6 work is done — don't wait for Aug 6.
