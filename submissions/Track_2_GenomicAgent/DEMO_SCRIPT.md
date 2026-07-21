# Demo Video Script — Genomic Research Agent (Track 2)

Built for Synthesia (free tier: 10 min/month, no credit card, watermarked —
plenty of headroom for this ~4 minute cut). Structure: a screen recording of
the real terminal session plays as the background/media track; a Synthesia
avatar narrates over it, either full-frame during the open/close or as a
picture-in-picture corner insert during the terminal segments (either works —
pick whichever Synthesia's editor makes easiest for a first try).

**Before recording:** run `cargo run --release` and `cargo run --release --
gpu-bench` in a terminal with large, readable font (18pt+, dark theme, high
contrast) and capture the screen. Don't narrate live — just capture clean
terminal output, since Synthesia's avatar does all the talking. Every number
below is real, copied from an actual run on this machine — if you re-record
and get slightly different numbers (GPU timing varies run to run), just
update the script, don't force the old numbers.

**The angle, stated up front:** most hackathon demo videos open with hype.
This one opens by contrasting *that* against what this project actually is —
a bet that a rigorously-verified, honestly-documented agent is more
persuasive than a flashy one. That's the hook. Lean into it — it's genuinely
different from the template every other submission will use.

---

## Scene 1 — Cold open (0:00–0:20, ~20s)

**Visual:** avatar, full-frame, plain background.

**Narration:**
> "Every hackathon demo says 'this is production-ready.' I'm not going to
> say that. What I'm going to show you instead is forty-two automated tests,
> a GPU kernel that cross-checks itself against a CPU reference on every
> single run, and a permutation test that once told me my own result
> *wasn't* statistically significant — and I kept that finding in the demo
> anyway. This is the Genomic Research Agent, and it's built to survive you
> actually reading the code."

---

## Scene 2 — What it is (0:20–0:55, ~35s)

**Visual:** avatar corner insert; terminal shows `cargo run --release`
starting up, six query headers scrolling past.

**Narration:**
> "It's an agentic AI for population genetics. Six real tools — variant QC,
> linkage disequilibrium, haplotype tallying, PCA-based ancestry structure,
> confidence intervals, and a selection scan. A natural-language query gets
> routed to the right tool, or tools, automatically. Here's the part that
> usually needs an LLM API call: this routing is a custom, from-scratch GPU
> kernel I wrote — Okapi BM25 with bigram features, dispatched on the AMD
> GPU. Zero API key. Zero network call. Zero cost. Watch."

---

## Scene 3 — Live multi-tool routing (0:55–1:35, ~40s)

**Visual:** terminal, full-frame or avatar corner — the query "Run
population structure PCA to check for ancestry clustering" and its response
line.

**Narration:**
> "One query, three tools selected automatically — Population Structure,
> Selection Scan, and Haplotype Tool — each with a real relevance score you
> can audit right there in the output. Not a hardcoded list. That's a
> genuine GPU dot-product kernel scoring every tool's real description
> against the query in real time, on this machine's AMD Radeon 780M."

---

## Scene 4 — Real computation, not literals (1:35–2:10, ~35s)

**Visual:** terminal scrolled to the `VcfAnalyzer` and `SelectionScan`
output blocks.

**Narration:**
> "Every number here is computed, not printed as a string. A real
> chi-square Hardy-Weinberg test — this run's worst-fitting SNP is right
> there with its actual observed and expected genotype counts. A real
> Wright's fixation index selection scan, with an empirical
> permutation-test p-value on every SNP — two hundred label reshuffles per
> SNP, not a bare number that looks scientific but isn't."

---

## Scene 5 — AMD GPU, cross-validated (2:10–2:50, ~40s)

**Visual:** terminal running `cargo run --release -- gpu-bench`, scrolled to
the adapter line and the two speedup rows.

**Narration:**
> "This explicitly targets AMD hardware — it enumerates GPU adapters and
> prefers the AMD device, here a Radeon 780M, over any other GPU present.
> And every GPU result is cross-checked against a CPU reference on every
> run — max observed difference, two millionths, float rounding, nothing
> more. At four thousand SNPs, five hundred eighty-five thousand pairs, the
> GPU path runs three and a half times faster than CPU. That's not a
> one-time benchmark — it's the actual code path this agent runs every
> time."

---

## Scene 6 — Local LLM inference on the AMD GPU (2:50–3:35, ~45s)

**Visual:** terminal running `local-bench` (feature build), scrolled to the
device-pinning line and the GPU-vs-CPU comparison block.

**Narration:**
> "And here's the part most submissions in this category skip entirely:
> real local AI model inference, running on this same AMD Radeon GPU — not
> a cloud API call. Llama-dot-cpp's Vulkan backend, a quantized
> one-point-five billion parameter model, actually loaded onto the GPU.
> This machine happens to have a second, discrete GPU too — so I made the
> code explicitly find and pin to the AMD device by name, and you can see
> it confirm that right here. Twenty-one tokens a second on the GPU, fifty
> percent faster than the same model run CPU-only, measured in the same
> pass. Real, modest, and honestly reported — not inflated for the demo."

---

## Scene 7 — Real data, not just synthetic (3:35–4:05, ~30s)

**Visual:** avatar corner; terminal running the same demo with
`GENOMIC_AGENT_REAL_DATA=1` set, scrolled to an LD block result.

**Narration:**
> "Every tool also runs against a real, bundled slice of the actual 1000
> Genomes Project data — a real mitochondrial genotype callset, not another
> synthetic generator pretending to be real. Real biology, real noise, real
> results — including one place where the honest answer was 'not
> significant,' which is exactly what a rigorous test is supposed to
> sometimes say."

---

## Scene 8 — Close (4:05–4:25, ~20s)

**Visual:** avatar, full-frame.

**Narration:**
> "Forty-two tests. Zero compiler warnings. Every claim in the README backed
> by a command you can run yourself. This is the Genomic Research Agent —
> built for the AMD AI DevMaster Hackathon, Track 2, and built to hold up
> under exactly the kind of scrutiny a judge is going to give it."

---

## Notes for recording

- Total runtime: ~4 minutes 25 seconds — comfortably inside the 3-5 minute
  guidance and Synthesia's 10-minute free-tier cap.
- If Synthesia's editor asks for scene-by-scene text instead of one long
  script, the `##` headers above are already split into upload-ready chunks.
- Keep terminal font large and the window uncluttered — no other apps
  visible, no personal file paths in the prompt if that matters to you
  (this repo's paths are already generic enough, but check your own
  terminal prompt/title bar before recording).
- If any number drifts on your own machine's re-run (GPU timing is
  hardware- and load-dependent), update the script to match your real
  output rather than keeping these exact figures — the whole point of this
  video is that nothing in it is fabricated.
