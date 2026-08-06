# Demo Video Script — Knowledge Garden

> Duration: ~4 minutes 42 seconds. Recorded on the real AMD Radeon gfx1100
> GPU (ROCm 7.2.x). English narration + burned-in subtitles.
>
> Video: `docs/demo/knowledge-garden-demo.mp4`
> Subtitles: `docs/demo/subtitles.srt`

The narration below matches the recorded demo one-to-one.

---

## T+0:01 — Welcome

*Screen: garden overview — skill garden with growth values and status.*

> Welcome to Knowledge Garden — a private learning companion Agent that runs
> entirely on a single AMD Radeon gfx1100 GPU with ROCm. In this demo, we
> will learn the Raft consensus algorithm from scratch, using only locally
> deployed open-source models.

## T+0:22 — GPU verification

*Screen: rocm-smi output — one AMD Radeon card, 48 GB VRAM, 41.7 GB used.*

> First, let us verify the GPU is real and active. The ROCm System
> Management Interface shows one AMD Radeon graphics card with 48 gigabytes
> of VRAM — and 41.7 gigabytes are currently in use by two models running
> simultaneously. No cloud GPU, no external API — everything on this card.

## T+0:46 — Model check

*Screen: vLLM endpoints — Qwen2.5-14B-AWQ :8000, Qwen2.5-32B-AWQ :8001.*

> Two models are served by vLLM on ROCm through OpenAI-compatible endpoints.
> Qwen2.5 fourteen billion, AWQ four-bit quantization, handles the
> interactive dialogue layer at twenty-six tokens per second. Qwen2.5
> thirty-two billion handles batch extraction at twelve and a half tokens
> per second. AWQ quantization gives us two point one times the speed of the
> original floating point format.

## T+1:16 — Routing decision

*Screen: garden overview (return).*

> Our routing decision between Qwen models was validated by an offline A-B
> test, documented in the repository. The Qwen3 thinking model was
> evaluated, but Qwen2.5 thirty-two billion won on grading consistency. We
> chose performance and reliability.

## T+1:36 — The garden

*Screen: garden — skills as plants, growth values, status.*

> Now, the Knowledge Garden interface. Each skill is a plant in the garden
> — its growth value and mastery status are visible at a glance. Today, we
> will plant a new seed: Raft consensus, a distributed systems topic.

## T+1:51 — Upload a Markdown file

*Screen: upload page — drop zone, file selected, filename shown, no text echo.*

> We navigate to the upload page. The agent accepts Markdown study material
> only — dragged or dropped directly into the drop zone. We select our Raft
> notes file. Notice: the file name appears, but the content is not echoed
> into any text field — it is uploaded and stored as the original source
> document.

## T+2:11 — Extraction starts

*Screen: processing page — queued → running.*

> We create the import. The material is sent to the local thirty-two billion
> batch model, which extracts knowledge units and validates them against the
> source. Here on the processing page, the job is queued and running.

## T+2:26 — Verified automatically

*Screen: processing page — verified badge, no manual refresh.*

> The extraction completes automatically — no manual refresh needed. The
> page updates by itself when the job reaches the verified state. All
> knowledge units have passed source validation and entailment checks.

## T+2:39 — Skill detail

*Screen: skill detail — verified units with source spans and key points.*

> Let us open the skill detail page. We can see the extracted knowledge
> units, each with its source span and key points. The verified units are
> ready for learning.

## T+2:58 — Source document viewer

*Screen: source page — original Markdown rendered with headings, bold, lists.*

> From a knowledge card, we can open the original source document. The
> uploaded Markdown is rendered as formatted text — headings, bold, lists,
> all intact. This is the traceability guarantee: every knowledge unit can
> be traced back to its exact source.

## T+3:11 — Feynman learning

*Screen: learn page — prompt + draft area.*

> Time to learn. Knowledge Garden applies the Feynman technique: we recall
> the concept in our own words. The agent prompts us to explain — for
> example, how does Raft elect a leader? We type our explanation into the
> draft area.

## T+3:22 — Feedback

*Screen: learn page — submitted draft, structured feedback.*

> We submit our recall. The fourteen billion dialogue model evaluates our
> answer against the source material, and gives us structured feedback with
> the correct explanation.

## T+3:38 — Assessment

*Screen: assessment page — recall input, answer never revealed.*

> Next, the first assessment. The agent tests our understanding with
> source-grounded recall — the answer is never revealed, only our memory is
> exercised. This is the spaced repetition foundation.

## T+3:53 — Review

*Screen: review page — due review, hidden answer, source hint.*

> Finally, the review flow. Knowledge Garden schedules reviews using the
> SM-2 spaced repetition algorithm based on the Ebbinghaus forgetting curve.
> Due reviews resume automatically with hidden answers.

## T+4:08 — The loop closes

*Screen: garden — the new skill has grown.*

> Back in the garden, we see our new skill has grown. The learning loop is
> complete: upload, extract, learn, assess, review. And the entire pipeline
> — from the web interface to the thirty-two billion model — runs on one AMD
> Radeon GPU.

## T+4:28 — Thank you

> Thank you for watching. Knowledge Garden — a private, local learning
> companion, powered by AMD Radeon and ROCm.
