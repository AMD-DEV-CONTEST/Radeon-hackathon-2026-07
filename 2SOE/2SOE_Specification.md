# 2SOE — Project Specification Document

**Sovereign Security Orchestrator Engine**

**AMD AI DevMaster Hackathon — Track 2: Development & Local Deployment of Private AI Agents**

| | |
|---|---|
| Team | **2SIN** — Souveraineté, Sécurité et Indépendance Numérique — solo submission |
| Author | Thierry Rolland, alias Thoun — engineer, fifteen years of critical IT infrastructure |
| Application | **2SOE** — Sovereign Security Orchestrator Engine |
| First instance | French property-law assistant for management firms and law offices |
| Demonstration video | https://youtu.be/DUxTtCCJG9Y (4 min) |
| Unedited W7900 capture | https://youtu.be/meM1-1A_l4w (40 s) |
| Raw benchmark output | `proof/` — five runs, two GPU architectures |

> **Prerequisite — the system operates in French.** 2SOE serves French property
> law to French firms: the corpus, the security socle, the semantic firewall and
> the domain measurement are all built on French. Input in another language is
> outside the intended scope (see §7.4). Interface and answers are in French;
> this document is in English.

---

## 1. Application scenario

### 1.1 The problem

French real-estate management firms and law offices face a specific constraint: a
wrong legal citation is not a minor inconvenience, it loses the case. A manager
who quotes "article 15 of the Civil Code" when the rule actually sits in a
non-codified statute has produced a document that cannot be used.

General-purpose AI assistants fail here for two reasons, and neither is solved by
using a larger model:

- **they invent** — a language model optimises for plausibility, never for
  conformity. Two equally plausible outputs are equivalent to it; nothing inside
  it prefers the correct one;
- **they cannot be audited** — the professional cannot tell which part of an
  answer is grounded and which was produced from the model's weights.

### 1.2 Why local

Legal professionals are bound by professional secrecy. Client data — names,
addresses, amounts, disputes — cannot transit through a third-party API. This is
not a preference but a regulatory constraint, and it makes local deployment the
only viable architecture for this market.

2SOE runs entirely on the user's own hardware: model, vector store, memory,
document generation. No remote API is involved in any core function.

### 1.3 Target users

- real-estate management firms (rental management, co-ownership)
- law offices specialising in property law

### 1.4 What the system does — and does not

The assistant answers questions on French property law from a verified corpus, drafts
formal documents (formal notices, rent reminders, notices to quit), and refuses
to answer when it has no source.

It is **an assistant, not a decision-maker**. The core guarantees properties —
no ungrounded answer, no cross-profile access — and a human decides and remains
responsible.

---

## 2. Agent architecture

### 2.1 The founding principle: the workflow decides, the model executes

This inverts the usual agentic pattern. In LangChain, AutoGen or CrewAI, the
model chooses its tools and plans its steps — which makes behaviour
non-deterministic and unauditable.

In 2SOE, a **declarative JSON program** drives the sequence. The LLM is one
primitive among others, called only when the workflow prescribes it.
Non-determinism is confined to a single organ.

The separation is explicit: **framework ↔ workflow ↔ `*.json`**. The framework is
generic and knows no trade; the workflow declares the sequence; the JSON files
carry it. Changing the behaviour means editing a declaration, not the engine.

**The engine was written from scratch.** An existing agentic framework would have
provided composition too — but by handing it to the model: which tool to call,
how many times to loop. What must be guaranteed would have become emergent.

That choice has a second consequence, rarely stated. Emergent composition
requires a model able to carry it: choosing tools, holding a long loop, staying
coherent over tens of thousands of tokens. Declared composition requires nothing
of the model — the file composes, the model only understands and rephrases. The
first needs infrastructure a law firm cannot afford; the second runs on two
consumer GPUs.

**Declaring the composition does not only make it auditable — it makes it
affordable.** Both properties follow from the same decision.

**Everything that defines behaviour is declarative.** The workflow, the skills,
the document templates, the access profiles, the sensitive-domain firewall, the
corpus itself — all JSON; the security socle and the behavioural fragments live
as vectors. The engine knows nothing about law: it reads a program and runs it.
Changing business domain means changing data, not code. Several of these files
are re-read on every request, so a firewall rule or an access profile can be
adjusted without restarting anything.

### 2.2 System diagram

```
browser ──> auth (JWT) ──> relay ──────────────> vLLM (Mistral 7B, AMD Radeon)
                             │
                             ├── workflow engine (declarative JSON)
                             ├── 23 primitives (the organs)
                             └── core: firewall, abstention, fidelity check
                             │
        PostgreSQL (accounts, decision journal)
        Qdrant (corpus, security socle, memory) + TEI (BGE-M3 embeddings)
        Redis (hot memory, differentiated TTL)
```

Eight services, orchestrated by `docker compose`, on a single bridge network.
Services resolve each other by name; no hardcoded addresses.

### 2.3 Body and fluid

The architecture rests on one partition, verified twice on unrelated ground
(telecom command generation in 2024, legal document generation in 2026):

```
BODY  (core)    what must be GUARANTEED or TRACED  → deterministic
                abstention, firewall, fidelity check, partitioning
FLUID (model)   what must be ADAPTED or UNDERSTOOD → variable
                language, phrasing, comprehension
```

The rule that follows: **what must be guaranteed is never made conditional.**
The model proposes; the core decides how many retries are allowed; the human
decides and commits.

### 2.4 Six response paths

A request enters the workflow and takes one of six paths:

| path | behaviour |
|---|---|
| `firewall` | sensitive domain (distress, medical, pharmacological, financial) — **the model is never called**, the core answers and stops |
| `hors_domaine` | a legal question, but outside the covered domains — abstention, no invented answer |
| `hors_droits` | a legal code the user's profile does not open — abstention by partitioning |
| `hors_corpus` | legitimate legal question, no source available — **structural abstention** |
| `libre` | not a professional question at all — brief bounded answer, no corpus, no citation |
| `corpus` | covered by a source — grounded, cited, fidelity-checked answer |

---

## 3. Core capabilities

All five capabilities requested by Track 2 are implemented.

### 3.1 Local knowledge retrieval (RAG)

Qdrant vector store, BGE-M3 embeddings served by TEI. The legal corpus holds
**127 points across 6 collections** (five codes plus case law), each article
verified against **Légifrance**, the official French legal publication service.

Five mechanisms beyond plain similarity search:

- **lexical coverage check** — similarity score alone cannot decide coverage:
  in-corpus and out-of-corpus score populations *overlap* (measured: in
  0.501–0.692, out 0.510–0.575). Geometry ranks correctly; the core verifies
  whether the retrieved article actually addresses the subject.
- **subdivision splitting** — an over-long article drowns the answer. Articles
  are split by legal subdivision (~2500 characters), which removed spurious
  citations and cut served context by a factor of three.
- **explicit references override the score** — a question naming an article
  (`article 24`, `L145-5`, `loi 89-462`) is extracted by regular expression and
  served by filtered scroll, bypassing semantic thresholds entirely. A citation
  is an objective fact; it has no business being measured.
- **the entry firewall settles domain membership** — once it has classified a
  request as trade-related, intent measurement no longer re-litigates that
  question; it only chooses between trade domains. Without this, two organs of
  the same core returned opposite verdicts on the same request.
- **an undecidable request is not decided** — a question carrying too few
  meaningful terms is marked *imprecise* **before** any acceptance criterion is
  examined. Measured: "cela fait partie de quel article" (*which article does
  that belong to*) was previously served a corpus through lexical coverage alone
  — the word *article* appears in nearly every point of the corpus — and the
  model answered on it. A citation exempts from this test: naming an article is
  an objective fact, not something to be measured.
- **one enriched retry** — when a request is undecidable and a previous turn
  exists, the whole workflow is replayed on the concatenated question, entry
  firewall included, exactly as if the user had written it in one go. One retry
  only: if the result is still undecidable, the system asks.

### 3.2 Tool invocation

Primitives are the tools, declared in a registry and called by the workflow.
Document generation (docx, PDF, Markdown) runs inside the relay, with no external
agent. The model fills **variables only**; the text itself comes from a template —
it never writes a sentence of the final document.

### 3.3 Multi-step task planning

The declarative workflow drives the sequence, with conditions, bounded loops
(1 to 3 passes depending on declared complexity) and flow interruption on guard.

**Skills** compose further work: a skill is a child workflow reusing the same
primitives through the same engine. Two natures, distinguished by their call
path, not their content:

- **competence** — reached by semantic routing; the caller discovers what it will do
- **application** — invoked by name; the caller expects a precise result, so it
  declares its output contract

A skill is executed by the **same engine**, on a copy of the context, with a
depth guard. The engine therefore composes recursively: a parent workflow can
call several children, each with its own corpus, its own primitives, its own
thresholds.

**Multi-expert composition is already available** — within a single process, with
no network transport. Distribution across separate relays remains future work,
and is only worth its cost where fault isolation, independent scaling or separate
deployment are required.

### 3.4 Local multi-turn memory

Three tiers, each with its own relation to time:

| tier | store | law |
|---|---|---|
| short | Redis | sliding, differentiated TTL: technical context 1 h, **sensitive data 5 min** |
| working | Qdrant `memoire_svo` | semantic resonance, 7-day TTL — **orients retrieval, is never quoted** |
| long | Qdrant `memoire_chemin` | persistent trace that a topic was discussed, **without its content** |

The 5-minute TTL on sensitive data is not a performance setting: it is
professional secrecy written into the lifetime of the data.

### 3.5 Permission control and privacy

- **JWT authentication** in a dedicated service; the relay never sees credentials,
  it receives an already-authenticated identity
- **corpus partitioning** by profile: the intersection domain ∩ profile is computed
  *before* querying the vector store — out-of-profile corpus is never searched,
  not filtered afterwards
- **semantic firewall** as the first organ of the flow, on live configuration
- **partitioning holds under load** — measured with 6 concurrent sessions on
  different profiles: no cross-session leakage

Partitioning refuses rather than falls back. Each domain declares a
**characteristic collection** — the one without which the domain cannot be
treated. If the profile does not open it, the request is refused outright; there
is no retreat onto whichever collections the profile does happen to hold.

This was learned from a measured failure: a residential profile asking about
commercial leases received article 11 of the 1989 statute, and the model
completed the rest from its weights. **Answering beside the question is worse
than abstaining — the user believes he has been informed.**

---

## 4. Model and local deployment

### 4.1 The served model

**Mistral-7B-Instruct-v0.3**, served by vLLM on AMD Radeon with ROCm.

The choice embodies the project's thesis: **a 7B model, governed by the core and
fed by verified retrieval, is enough**. Size is not the reliability lever.

### 4.2 The model is an interchangeable organ

Changing the model is a configuration change, not a code change. `VLLM_MODEL`
drives both the inference server and the relay, so they cannot diverge.

Interchangeability is not free, and the architecture pays its cost explicitly:
each model has its own geometry and reacts differently to the same system prompt.
The security socle therefore carries a **`modele_cible` field** — prompt variants
follow the loaded model, and only what empirically diverges is duplicated.

The security socle itself is **incompressible**, guaranteed twice over: it is
retrieved by unfiltered scroll (never by score, never by model), and a minimal
fallback is embedded in the core should the vector store be empty or unreachable.
**The system never answers without its security socle.**

### 4.3 Deployment

```
docker compose up -d          # 8 services
<ingest corpus, socle, fragments, skills>
```

First start takes about 25 minutes on a cold cache (embedding model ~2 GB, LLM
~15 GB); health checks are sized accordingly. Subsequent starts take about a
minute.

The full reproduction procedure is in `README.md`.

### 4.4 Validated on the target platform

The submission was deployed and measured on **Radeon Cloud (W7900, gfx1100,
ROCm 7.2.1)**. The platform provides notebook pods with no Docker daemon, so the
services were run natively — which turned out to be the more valuable test:
**the architecture does not depend on Docker**. The engine, primitives and core
are plain Python; the compose file is an orchestrator, not a dependency.

Every data path is anchored on the file's own location rather than on a fixed
directory, so the package follows the repository wherever it is cloned. The
target-platform run above was performed with **no path variable set at all** —
only service URLs and credentials.

The environment was rebuilt **entirely from scratch** on a freshly provisioned
instance: a `git clone` of this repository, services installed and started one by
one, corpus ingested from the shipped JSON. Nothing was carried over from the
development machine. Different GPU architecture, half the GPUs, no container
runtime — same result. The generated PDF came out under
`relay/framework/primitives/../../out/`: a relative path, on a machine sharing
nothing with the development host.

One difference is worth stating plainly: TEI could not be installed on that
platform — its release binaries are unreachable from that network and it is not
published on PyPI. It was replaced by a minimal server exposing the same
`/embed` endpoint with the same **BGE-M3** model and the same 1024-dimension
output. The embeddings are BGE-M3 either way; the serving implementation
differs.

---

## 5. Inference optimisation on AMD Radeon

### 5.1 The strongest optimisation is the call that is never made

Before any kernel-level consideration, the architecture removes work:

- **the entry firewall stops sensitive requests before the model is called** —
  no inference at all on out-of-scope domains
- **abstention is a core function** — when no source grounds the answer, the
  model is not called to fill the gap. It is not asked to say "I don't know";
  it is simply not invoked
- **document generation calls no model for the text** — the template imposes the
  wording; the model only fills business variables
- **the engine skips model calls when the turn cannot proceed further**

Measured effect on the benchmark: five of twenty cases complete in **0.0–0.5 s**
because they never reach the LLM.

Context is sized to the workload rather than to the model ceiling: a legal
consultation serves around 8,000 tokens — **2.6 % of the available KV cache**.
The limiting factor is not the hardware. Reducing what is served is a quality
decision, not an economy: the model mirrors its input, and a mirror does not
sort.

### 5.2 Serving measurements (2× Radeon AI PRO R9700, TP=2, ROCm 7.2.4)

```
KV cache                359,888 tokens (21.97 GiB)
Prompt throughput       936 tokens/s
Generation throughput   54 tokens/s
End-to-end retrieval    ~100 ms (72 ms embed + 26 ms vector search)
```

Reading is cheap, writing is expensive — which is why serving a larger corpus
costs almost nothing, while response length dominates latency. Context served per
consultation is ~8,000 tokens, so the KV cache supports roughly 45 concurrent
consultations: about ten simultaneous users without queuing.

### 5.3 Corpus splitting: context divided by three

Article 24 of the 1989 statute ran to 14,412 characters as a single chunk. Split
by legal subdivision (~2,500 characters per point), the served context dropped by
a factor of three **and** spurious citations disappeared. Less context, better
answers.

### 5.4 Concurrency: 4× speed-up, no loss of correctness

The measurement bench runs in two regimes on identical cases:

| regime | duration | correctness | contradictions |
|---|---|---|---|
| sequential | 3 min 10 | 100 % | 0 |
| 6 concurrent | **45 s** | 100 % | 0 |

vLLM's continuous batching gives a **4.2× speed-up with no degradation** — and no
cross-session leakage, which is what makes the multi-tenant claim measurable
rather than asserted.

The same ratio was measured on the target platform with a **single** GPU
(§6.5). Durations shift from one run to the next; correctness does not (§6.4).
The figures above are measured runs, not guaranteed latencies.

### 5.5 Model size measured, not assumed

Same core, same corpus, same socle, same image — only the model changes:

| model | correctness | sequential |
|---|---|---|
| **Mistral 7B** (dense) | **100 %** (20/20) | **3 min 10** |
| gpt-oss 20B (MoE) | 94–96 % (17–18/20) | 6 min 48 – 7 min 35 |

A model **three times smaller** is **twice as fast** and **more correct** than the
larger one, on the same core — each model receiving its own security socle, so
the comparison holds on equal terms.

Both gpt-oss runs missed the same article — `L145-4`, commercial leases — on the
same two cases. That is a reproducible gap in one region of the model, not noise:
two geometries, two behaviours.

A third model, Mistral Small 24B, could not be measured on this stack: an
upstream tokenizer defect in vLLM returns raw BPE markers instead of decoded text
for that model family. The defect is documented publicly and lies outside our
scope — **no conclusion is drawn about that model's capability from a broken
environment.**

The same observation was made independently against hosted APIs, where no such
defect applies: asked about a notice period, a larger hosted Mistral model
attributed the rule to "article 15 of the Civil Code" — a non-codified statute
misfiled — while the local 7B, governed by the same core, cited the 1989 statute
correctly.

This is the practical form of the thesis: reliability comes from governance, not
from parameter count — and governance is what makes small models deployable on
accessible hardware.

### 5.6 Platform adaptation

The stack is parameterised for the target GPU: `VLLM_IMAGE`, `VLLM_TP` (tensor
parallelism), `ROCM_ARCH`, `VLLM_MAX_LEN`. Defaults match the validated
configuration; a single GPU deployment needs only `VLLM_TP=1`.

Note on the gfx1201 architecture (RDNA 4): ROCm's GEMM optimisation libraries do
not yet support it, which cripples raw matrix benchmarks. Inference is unaffected
because vLLM uses its own attention kernels — a distinction worth making when
reading benchmark figures on recent AMD hardware.

---

## 6. Measurement

### 6.1 The system judges itself

The core already emits the signals needed to judge an answer: retrieval status,
grounding verdict, non-conforming citations, missing fields, abstention. **No
human annotation is required** — the bench compares what the system itself
observed.

20 cases across 8 families: corpus, out-of-corpus, firewall, drafting discipline,
partitioning, reference handling, free conversation, out-of-domain.

### 6.2 Form and correctness, deliberately separated

- **stability** across repeated runs — identical / compatible / CONTRADICTORY
- **correctness** — is the expected fact present?

The two verdicts must not be confused. **Compatible** means *incomplete but
correct*: one run develops an exception the other stops short of, and nothing in
either is foreign to the other — inclusion holds. **Contradictory** means either a
strict field diverges (retrieval status, abstention, produced document, leading
figure, amounts) or an element appears that belongs to neither set — something was
asserted that the others exclude.

A contradictory verdict therefore says nothing about completeness: a run may be
contradictory *and* incomplete. What is hunted is contradiction, not brevity.

This separation matters. One case — the notice period given by the *landlord* —
regularly returns CONTRADICTORY while scoring 100 % correct. The rule is
genuinely multiple (six months in principle, different rules for repossession,
sale, location), so different runs surface different facets, all of them true.
**The bench does not confuse "the model contradicts itself" with "the model is
wrong."**

### 6.3 How the score is computed — and what it does not prove

A number is worth what its method is worth. Correctness is computed by confronting
the **facts observed** against the **expectations declared** by each case:

```json
"attendu": {
  "rag_statut": "servi",           ← state emitted by the core
  "domaine": "baux_habitation",    ← state emitted by intent measurement
  "article": "15",                 ← extracted from the answer
  "citations_non_conformes": 0     ← state emitted by the fidelity check
}
```

Five of the six criteria compare **state the core itself emitted** — retrieval
status, measured domain, intent, abstention, produced document, missing fields.
None is a text match against a hand-written reference answer. Faking them would
require the system to lie about its own execution.

Two further design decisions matter. Article references are normalised before
comparison (`L.145-4`, `L145-4`, `L 145-4` are the same reference), which removes
formatting noise without widening the target. And an expectation the harness
cannot measure is **removed from the denominator** rather than counted as failed —
no manufactured failure, and no manufactured success either.

**What the figure does not prove.** Three limits, stated so that the reader does
not have to find them:

- the `article` criterion tests **presence, not exclusivity** — a response citing
  the right article *and* a wrong one satisfies it. The wrong citation is caught
  by a separate mechanism (`citations_non_conformes`), declared only on some
  cases;
- **the cases and their expectations are written by the author**, in the same
  file, on a corpus he assembled. `benchmark_cas.json` ships with the submission
  precisely so that this can be judged rather than trusted;
- **the denominator varies per case** — a case with one criterion weighs as much
  in the average as a case with four. "100 % correctness" means *every declared
  criterion was satisfied*, not *the system is perfect*.

What the bench does prove is that it detects its own defects: it is what surfaced
a corrupt corpus field, a truncated security socle, and three extraction faults
during development — each time by dropping below 100 %, never by staying there.

### 6.4 A third axis: duration is not predictable per request

The bench also records durations, and they behave chaotically. The organ trace
makes the phenomenon precise. Same machine, same configuration, same corpus — the
same question asked twice:

| organ | pass A | pass B |
|---|---|---|
| firewall | 0.00 s | 0.00 s |
| intent measurement | 0.59 s | 0.60 s |
| retrieval | 0.18 s | 0.17 s |
| **model call** | **10.12 s** | **5.42 s** |
| fidelity check | 0.00 s | 0.00 s |

The four deterministic organs are stable to the hundredth of a second. **Only the
model call moves — by a factor of two.** This is not measurement noise: the model
emits a different number of tokens at each pass, developing an exception here and
omitting one there.

Aggregates move far less than individual cases: across runs the total varies by
under 10 %, while a single case can shift by 77 %.

**This breaks a property that infrastructure engineering takes for granted.** A
telecom minute is a minute. A network packet has a bounded size. A protocol has a
computable throughput, so it can be dimensioned and billed from usage. A language
model has no such stable unit: the same request, in the same state, consumes a
different token budget every time.

Three consequences follow, and they are practical:

- **no per-request latency guarantee is honest** — only aggregate averages carry
  meaning;
- **no per-request cost can be budgeted precisely** — which is a further argument
  for local deployment, where the cost is the hardware and therefore fixed;
- **dimensioning is done on volume**, exactly as a network is dimensioned on
  aggregate traffic rather than on the size of one packet.

Put together with the two axes above, the bench measures three independent
dimensions where common practice measures one:

```
form         varies   (14 → 19 identical runs out of 20)
duration     varies   (up to ±77 % on a single case)
correctness  stable   (100 % in every run, on both platforms)
```

### 6.5 Results

Development platform (2× Radeon AI PRO R9700, gfx1201, TP=2, Docker):

| regime | identical | compatible | contradictory | correctness | duration |
|---|---|---|---|---|---|
| sequential | 17/20 | 1 | 2 | **100 %** (20/20) | 3 min 10 |
| concurrent (6) | 19/20 | 1 | **0** | **100 %** (20/20) | 45 s |

Target platform (Radeon Cloud W7900, gfx1100, **single GPU**, native deployment,
no Docker, no path variable set):

| regime | identical | compatible | contradictory | correctness | duration |
|---|---|---|---|---|---|
| sequential | 16/20 | 4 | **0** | **100 %** (20/20) | 7 min 46 |
| concurrent (6) | 17/20 | 3 | **0** | **100 %** (20/20) | 1 min 50 |

The two contradictory verdicts in the first run are cases `c02` and `c16` — the
landlord's notice period and a cited reference, both described in §6.2. Both
scored 100 % correct: the rule they cover is genuinely multiple, so different
passes surface different facets, all of them true. *Contradictory* is a verdict on
**form**, and it is reported rather than smoothed over.

The submission reaches the same correctness on the contest platform as on the
development machine — on a different GPU architecture, with half the GPUs,
deployed natively, without Docker, and without a single path variable set. Raw
output for all four runs is in `proof/`.

**What varied, and what did not.** Across runs on two GPU architectures, the
number of byte-identical runs ranged from **14 to 19** out of 20, and durations
moved by up to 77 % on a single case — while **correctness never moved: 100 % in
every run**. Stability of *form* and *duration* are properties of the model and
shift between executions; correctness is a property of the core and does not.
That is the thesis in measured form.

A system returning identical answers every time would prove nothing — it could be
a cache. Here the model rephrases at each pass, and the core guarantees
regardless.

---

## 7. Known limitations

### 7.1 Guarantees that are incomplete

- **Fidelity checking covers quoted citations.** Paraphrased numeric claims
  ("three months", without quotation marks) are not yet verified
  character-by-character — and that is precisely where the model's known weakness
  lies. Measured on a generated document: asked for arrears covering *March to
  May*, the model returned *May*. Twice, in separate sessions. A prompt-level fix
  — explicit prohibition, two interval examples — had **no effect** and was
  reverted. The correction that would hold is deterministic: the retained value
  must be found in the original request. *A directive is a hope; a guarantee is
  an organ.*
- **There is no confidentiality firewall on output.** The model is porous; we
  have measured it. What is guaranteed today is that the core does not leak, not
  that the model cannot be induced to.

### 7.2 The corpus can be wrong — and the model will repeat it faithfully

This is the hardest limitation, and it was demonstrated on our own corpus: a
metadata field wrongly attributed two non-codified statutes to the Civil Code.
The system then answered "article 15 of the Civil Code" — **not a hallucination,
a faithful reproduction of a corrupt source**. The anti-hallucination guard is
powerless in that case, because nothing is invented.

Corpus integrity is governed manually (official sources, verification,
versioning). **It is not automatable, and it is not delegable.**

The corpus itself is a demonstration corpus — 127 points, five codes — not
exhaustive legal coverage. A legitimate property-law question outside it returns
an abstention.

### 7.3 The corpus speaks statute, users speak trade

A property manager says *bail vide*; the statute says *bail d'habitation non
meublé*. Measured on three phrasings of the same question, all three retrieving
the right article:

| phrasing | outcome |
|---|---|
| *bail vide* | abstains |
| *bail non meublé* | answers |
| *logement loué vide* | answers, article 15 cited |

Retrieval succeeded every time — `rag_statut: servi`, with "three months" present
in the served context. **The behaviour turns on one word, not on a readable
rule.**

This is neither a retrieval defect nor a model defect: it is a **vocabulary gap
between professional usage and the legal source**. And the abstention it produces
is the intended behaviour — the socle forbids assuming an equivalence that no
source establishes. The fix is therefore not to loosen the socle, but to record
the equivalence as a **fact in the core**: a lexical layer determined by the
declared trade, so that the mapping is stated once rather than guessed at each
turn.

### 7.4 Language

The system operates **in French**. The semantic firewall matches French keywords
and domain measurement uses French-built vectors. Input in another language would
be neither correctly guarded nor correctly routed. This is a scope decision for a
French legal product, not an oversight — but it is a real boundary.

### 7.5 Memory partitioning is not yet complete

Free-path conversation and business work share one working-memory space. A
stop-gap prevents a guarded path from writing business traces; the full fix —
separate spaces, so the free path keeps its own long memory without touching the
business one — is scheduled and documented.

### 7.6 Document ingestion is not implemented

The interface exposes a document attachment control, deliberately disabled.
Files can be received and stored, but their content is not extracted, indexed or
made available to retrieval. The channel stays closed **by design**: it has no
equivalent of the semantic firewall that guards text input. Any ingestion
pipeline must carry that guarantee before the channel is opened.

### 7.7 The interface

The web UI is a working test surface, not the product. It exists to exercise the
agent; polish was not the objective within the project's timeframe.

---

## 8. Credits

The vLLM container image used on the development machine is built by **Donato
Capitella (kyuz0)** —
[amd-r9700-vllm-toolboxes](https://github.com/kyuz0/amd-r9700-vllm-toolboxes).
The build patches vLLM before installing it, then compiles it for the Radeon
R9700. The decisive change is a **substitution of the architecture reference**:
`gfx1201` is mapped to a CDNA device in AITER's arch detection, and added to the
professional-GPU whitelist. AITER's optimised paths — which upstream reserves for
AMD datacenter cards — are thereby activated on an RDNA 4 board. A stock image
cannot carry that substitution, which is why the image is built rather than
pulled. Without this work, running vLLM on this hardware would not have been
possible.

Legal corpus verified against **Légifrance**, the official French legal
publication service.

---

## 9. Summary

2SOE is a sovereign, deterministic agent framework in which a declarative program
governs decoupled organs — the LLM being one of them — to produce behaviour that
is auditable, guaranteed and entirely local.

The legal assistant is its first instance, built on a demanding domain:
professional secrecy makes local deployment mandatory, and a wrong citation loses
the case.

What the submission demonstrates, measured rather than claimed:

- five of five requested Track 2 capabilities implemented
- 100 % correctness on both the development machine and the target W7900, in
  sequential and concurrent regimes alike — raw output in `proof/`
- zero contradictions under concurrency, no cross-session leakage
- a 7B model outperforming a 20B one on the same core — **governance, not size**
- deployment validated under Docker and natively, on two GPU architectures, the
  second rebuilt from scratch out of this repository alone
