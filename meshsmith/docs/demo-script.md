# Demo video — shot list & narration (target 3:30–4:30)

Record at 1920×1080. Terminal font ≥16pt. Screen-record the Gradio tab + one terminal.
**Every generation shown on screen runs on the AMD Radeon GPU — keep the header banner
visible whenever possible.**

| t | Shot | Narration (spoken or captions) |
|---|---|---|
| 0:00 | Title card: "MeshSmith — text to physical object, fully local" | "This is MeshSmith: type a prompt, get a 3D-printable STL and a game-ready GLB. No cloud. One GPU." |
| 0:15 | Browser: app header, zoom on banner "AMD ROCm · Radeon …" | "Everything you'll see runs locally on an AMD Radeon GPU through ROCm — SDXL-Turbo, u2net and Hunyuan3D-2, chained in one pipeline." |
| 0:30 | Type: *"a chess knight piece, ornate baroque style"* → Forge (standard). Show stage progress ticking | "One click. Text to image, automatic subject cutout, image to 3D — watch the stage timer." |
| 1:10 | Result appears: orbit the GLB in the viewer, switch material preset, re-forge draft to show speed | "Here's the part most generators skip: this mesh is already repaired — watertight, de-floatered, decimated, UV-unwrapped, PBR material applied." |
| 1:50 | Scroll to summary: printability score, support-saved %, timings table | "MeshSmith also thinks like a printer. It scaled the knight to 80 millimeters, tried 26 orientations and picked the one that costs the least support — **read the support-saved figure off the screen** (across our benchmark runs it ranged 0–82%). It ray-samples wall thickness and scores printability before you waste plastic." |
| 2:25 | Open report.md side-by-side; point at bed-fit checks and wall stats | "The full report ships with every asset — machine-readable JSON too." |
| 2:45 | Image path: drop in a photo (e.g. a mug or a toy), Forge | "Already have a reference? Skip the prompt — photo straight to printable part." |
| 3:15 | Terminal: `python -m meshsmith.cli "a low-poly fox figurine" --quality draft` and `rocm-smi` in a split | "Same pipeline headless. Draft mode uses the distilled mini-turbo DiT — seconds per asset. That's rocm-smi showing the Radeon doing the work." |
| 3:40 | Show `docs/benchmark.md` table on the Radeon | "Reproducible numbers: the benchmark script rebuilds this table on any ROCm or CUDA machine." |
| 3:55 | Sliced STL in a slicer (PrusaSlicer/Bambu) — optional but powerful; else show the STL in the viewer | "The STL drops straight into the slicer." |
| 4:10 | End card: repo, MIT license, 'AMD AI DevMaster Hackathon Track 1' | "MeshSmith — open weights, open source, and the whole foundry is yours. Built on AMD." |

> Never quote a support-saved number from memory while recording — read whatever the run
> in front of you actually produced. The amphora legitimately scores 0% (already upright),
> and that is a good thing to say out loud: the optimiser leaves good orientations alone.

## Recording notes
- Do the standard-quality knight run once **before** recording so weights are warm.
- Keep one draft-quality run live on camera (fast); timelapse any standard run over 60 s.
- Capture `rocm-smi --showuse` in a visible split during generation for AMD proof.
- If recording via Radeon Cloud + rc-tunnel: browser shows the public URL of the app
  running on the Radeon box — that's fine, say "running remotely on a Radeon cloud GPU".
