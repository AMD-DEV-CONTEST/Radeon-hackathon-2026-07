# Phase 1 repository instructions

This directory implements Live Science Phase 1.

For every generation run:

- Treat `PHASE1_PROMPT.md` as the authoritative product and quality specification.
- Never hand-write or fake `bridge/manifest.json`; export it from the app's
  `LIVE_SCIENCE_BRIDGE` with `tools/export_bridge.mjs` so it matches rendered state.
- Treat the request file supplied for the run as the user input.
- Work end to end: understand, expand when educationally necessary, plan briefly, implement, render, inspect, repair, and validate.
- Write generated artifacts only inside the current run directory.
- Do not modify Phase 1 infrastructure, prompts, examples, or previous runs unless the task explicitly asks for infrastructure work.
- Prefer practical autonomy over lengthy status narration.
- Do not stop after producing a plan or a partially working animation.
- Use the provided renderer and validator when compatible; repair the app until validation passes.
- For `realizable` and `hybrid` routes, actually test both `clean` and `overlay`
  before finishing. If Bridge validation fails, fix the app or its Bridge metadata;
  do not bypass the validator.
- Keep planning artifacts lean. `brief.md` is enough unless the task genuinely requires something else.
- When delegating work to subagents, do not override the model or reasoning effort. Let every subagent inherit both settings from the agent that launched it.
