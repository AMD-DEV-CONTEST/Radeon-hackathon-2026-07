# omima — Astral Metro Domain

> **Submission**: omima · distributed private-agent OS  
> **Event**: 2026 AMD AI DevMaster Hackathon (global online) · Track 2: Development & Local Deployment of Private AI Agents  
> **Team**: kon (Luma registered name; no team name filled)  
> **Date**: 2026-07-29 (AMD / model-stack narrative aligned 2026-08-04)  
> **Submit**: PR → `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` (deadline 2026-08-06 23:59 UTC+8)  
> **Package index**: `00-PACKAGE.md` · AMD/ROCm chapter: `amd-rocm-technical.md` · English README: `README.en.md`

---

## Executive Summary

**omima — not chasing trends, filling a gap.**

Personal AI faces two dead ends: **send data to the cloud and lose privacy; let agents fight on their own and lose orchestration.** omima connects both paths — not by stacking another chat shell, but as a complete **efficiency-engineering** design.

### Converged statement (judges can read this first)

1. **Start**: the product is derived from **six classes of application needs** — basic capabilities, reasoning & science, dialogue & creation, knowledge & encyclopedia, safety & responsibility, long-context & agents (expanded into a six-class / ~28-task spectrum). Needs decide which algorithms and system capabilities to build.
2. **Converge to three pillars**:
   - **Systematized protocols & algorithms** (collaboration, boundaries, state replay);
   - **Internalized model settings** (1B / 9B / 35B job-role internalization, incl. training & serving parameters);
   - **Internalized working method** — **ideate → argue → plan → execute → review**, multi-agent **serial-stream with parallel steps**, every step auditable.
3. **Engineering facets**: one design covers **Harness** (tool constraints & experience reuse), **Loop engineering** (bounded multi-step, serial/parallel), **hardware staffing** (edge + constellation, role-to-silicon).
4. **Endpoint**: **high-satisfaction delivery** — needs covered, no overreach, auditable, long-horizon tasks complete the process.

Thesis (Chinese, canonical): **`core-thesis.md`**. Demo: **VOX explainer video** (3–5 min main / 90s short) per `demo-storyboard-vox.md` — infographic motion + voiceover, covering needs → three pillars → one task walkthrough → AMD measured numbers.

### Form summary

**omima** (Order Made In Mayhem, Always) takes the form of **Astral Metro Domain** — a **distributed heterogeneous star-network designed on the AMD compute base**, joined by the **Porphyrion protocol**, in three layers:

| Layer | Composition | Role |
|-------|-------------|------|
| **Tool side (harness / orchestration layer)** | Xagent (desktop, DEMO) · omima APK (mobile, DEMO) | User entry & orchestration: IronLaw, tool constraints, five-beat process, experience reuse |
| **Star-network POS layer (cheap compute)** | Stateless ECS / cloud-PC nodes (CPU-class) | Register capability, take task, execute, reply, forget |
| **Model layer (on demand)** | omima-1B router (resident) · 9B/35B job models (spun up on demand) | Router always-on, job models on demand; role-to-silicon. All three post-trained on AMD MI300X (ROCm) — AMD's pre-contest compute grant, **not a product runtime configuration** |

Layers are joined by the **Porphyrion communication protocol**: **stable long-lived connections + event callbacks**, working even on cloud PCs with **no port 22 and no public IP** — heterogeneous devices truly mesh; not one device against a super-monolith, but the **entire private star-network against a super-monolith**. Post-training and strategist validation happen on **AMD MI300X (ROCm)** — AMD's **pre-contest compute grant**, used to prove job models can go online; not offered as an omima product option (too specialized for ordinary users). Product runs on consumer-class hardware. See **`amd-rocm-technical.md`**.

---

## 1. Problem Definition

### 1.1 Your digital life has no OS

| Existing OS | What it manages | What omima manages |
|-------------|-----------------|--------------------|
| Windows / macOS | processes, memory, filesystem | attention, context, privacy boundary |
| Android / iOS | app lifecycle, notifications | cross-device task orchestration, heterogeneous compute scheduling |
| Cloud AI services | your data (uploads everything) | your data (never leaves the device) |

### 1.2 The three dilemmas of existing AI assistants

1. **Privacy dilemma**: ChatGPT/Gemini/Claude collect user data for training by default. omima's 1B Polaris converts intent into a pure task description locally and sends only that. **The cloud never touches your memory** — memory stays on the device; what leaves is a context-stripped task description.

2. **Cost dilemma**: cloud APIs bill per token; mature products price publicly — ChatGPT Plus $20/mo, Claude Pro $20/mo, GitHub Copilot $10/mo, Cursor Pro $20/mo. Heavy users burn tens of dollars monthly for "conversations that aren't remembered." omima's cost control is not about frugality — it is **reuse**: the cache-hit mechanism Xagent ported from Reasonix lets repeated parts of cloud inference hit cache directly, pushing the marginal cost of the DeepSeek API toward zero. This is verified in real usage (see §3.6 real ledger).

3. **Compute dilemma**: a phone agent is "congenitally weak" — a compute-starved short board. omima weaves scattered AMD devices into a private star-network via Astral Metro Domain: **35B-class heavy reasoning on unified-memory hosts or on-demand GPUs**, ECS CPUs for tool execution, phone GPUs for offline perception. CPU-class instances are orders of magnitude cheaper than GPU — daily tasks run on CPU instances; GPU appears only when truly needed. Not one device against a super-monolith — the **entire private star-network against one super-monolith**. (Note: MI300X is AMD's pre-contest training/validation compute, not a product runtime configuration.)

---

## 2. Why AMD — the contest is the entry, staffing is the bite point

To be direct: omima entered the AMD hackathon because AMD ran it. No deeper "philosophical necessity."

But "entering" ≠ "forced fit." omima's mode is **edge + constellation**: memory & routing at the focal point, execution spread across many machines, models staffed by role rather than crammed into a monolith. AMD's product spectrum — consumer NPUs, unified-memory clients, Instinct data-center cards, masses of x86 cloud instances — carries this staffing table:

| Mode role | Hardware placement (product expectation) | Contest main chain |
|-----------|------------------------------------------|---------------------|
| Focal point (router, resident) | Phone SoC; optional **Ryzen AI** | control plane & 1B role definition |
| Worker follow-through reasoning | **Ryzen AI laptop** (9B) | omima-9B trained on MI300X; CPU GGUF verifies tool-call |
| Strategist deep reasoning | **MAX 395+/400-class unified-memory host** (35B) | **MI300X** FP8 serving point + omima-35B LoRA |
| Star-node replication | EPYC / generic CPU cloud hosts + Xagent | production ECS star-network path |
| Train models / find working points | **MI300X** | primary experiment & weights evidence |

NVIDIA data center is a different track. omima neither disparages it nor dresses up "choosing AMD" as faith — **staffing needs layered silicon; AMD puts the layering in one worldview, and the contest provided hours on Instinct.**

Full 40-point AMD chapter (mode + primary data flow + experiments + boundaries): **`amd-rocm-technical.md`**. Evidence index: **`evidence/INDEX.md`**.

### 2.1 Model stack — 1B / 9B / 35B is staffing, not a shopping list

The mode requires three time scales at once: **always-online, daily execution, deep thinking**. One size cannot do all three.

| Model | Role | Deployment imagination | License / base |
|-------|------|------------------------|-----------------|
| **omima-1B** (Polaris) | sole memory holder · router · task stripping | phone-first "everywhere"; optional Ryzen AI resident | open weights; features staged |
| **omima-9B** | tool loops · follow-through reasoning · star-node Worker | product: Ryzen AI laptop; validation: CPU GGUF | MIT (Ornith-1.0-9B) |
| **omima-35B** | strategist · privacy-oriented deep reasoning | product: MAX-class unified-memory host; lab: **MI300X** | Ornith-1.0-35B LoRA / Qwen3.6-35B-A3B FP8 serving |

Deployment freedom remains: without local models you can use cloud APIs (see §2.3); with them, they go online by role.
**Weights & numbers shipped in this contest have primary evidence on MI300X (ROCm)** — see §2.2 and the chapter. Consumer machines are mode placement, not "benchmarked one by one in this contest."

Two inference tracks: edge/local role models for privacy & daily work; cloud DeepSeek etc. for peaks — Polaris routes, cloud holds no memory.

### 2.2 Post-training — for role readiness, not for show

Post-training, loss reduction, FP8 comparison — ordinary ROCm craft. omima does them because **staffing requires 9B/35B to genuinely work as agent parts**.

**Where**: AMD × ModelScope **MI300X** Notebook (ROCm · vLLM · PEFT LoRA; script `finetune_35b_lora.sh`).

**Data**:

| Tier | Content | Status |
|------|---------|--------|
| First-round role training | high-quality samples: tool sessions + architecture wiki (hundreds) | **trained into** omima-9B / omima-35B, pullable on ModelScope |
| Feed expansion | protocol schemas · session distillation · knowledge chunks (10k-scale slices) | **dataset-side ready** (`omima-training-data`); not claimed as "full second-round trained into 35B" |

**Verified records that happened** (ledger, not plan):

| Phase | Content | Result |
|-------|---------|--------|
| Phase 1 | 35B-A3B tool-calling | **8/9**, framework locked to vLLM ROCm |
| Phase 3 | FP8 vs BF16 | **~195 vs ~118 TPS (C=3, +65%)**, tool-call not degraded |
| Phase 4–5 role LoRA | omima-9B / omima-35B @ MI300X | 9B: Loss ~1.82→**0.79**, ~57min; 35B: Loss ~1.88→**0.96**, ~1h11m; serving ~**59–65 TPS** (short) |
| CPU role readiness | 9B GGUF Q8 | ~**13 t/s**, tool-call loop closed |
| Confidence | protocol-sample logprobs | unified threshold ~**0.72** (ask for help when uncertain) |

> TPS must be labeled by framework: vLLM numbers in the table above are serving-oriented; historical llama.cpp C=3 aggregate numbers, if cited, must be labeled separately — never mixed with vLLM in one cell.

**Assets**: `kooooon/omima-35B`, `kooooon/omima-9B`, `kooooon/omima-distilled`, `kooooon/omima-training-data` (ModelScope).

**Conclusion**: the protocol/role internalization pipeline runs on Instinct; the optimization objective is **"star-network roles can go online"**, not scattered tricks. Details & boundaries: **`amd-rocm-technical.md`**.

### 2.3 Inference routing: DeepSeek recommended for cloud — no hero worship, call on demand

**Facts first**: DeepSeek's capability is first-tier. Not our judgment — its own record: open weights, top evaluations, call cost an order of magnitude below closed rivals.

**Pricing** (official public): Claude Fable 5 (Anthropic's strongest) $10/MTok input / $50/MTok output; Claude Sonnet 5 from $3/$15; DeepSeek miss ¥2/MTok, cache-hit ¥0.2/MTok. The gap is not one order — it's two.

So the question: if capability is enough and price is low, why do many still feel "closed top models are better"?

Because **most people have not mastered the right way to use DeepSeek** (based on our observation of real development sessions).

- DeepSeek V4 covers the daily needs of the vast majority — code to plans, data analysis to Q&A
- But most use it as a chat window: context not reused, memory not kept, toolchain not organized, repeated questions paid for repeatedly
- The gap is not the model, it's the method

**Why no hero worship**: top closed models (Fable 5, GPT-5.6) are indeed stronger on long-horizon tasks — but C-end users generally have no long-horizon need; paying 10–50× for unused capability is consumerist. B-end long-horizon work should prioritize **methodology** (how context is organized, how toolchains flow, how memory is reused) over model selection. omima routes on demand: simple tasks to edge small models, complex tasks to cloud DeepSeek — no worship, what's usable counts.

**We studied Fable 5 — conclusion: "behavioral protocol is engineerable"**: community reverse-engineering suggests ~**70% of the gap vs previous flagship comes from behavioral protocol, not model capability** — pre-action reasoning rate 70.5% vs 47.5%, thinking depth, verification execution rate: all instruction-able behavioral differences. The protocol is portable: we distilled it into Xagent's operating procedure (10-line anchoring procedure + 6-beat thinking template + verification standards), the default working mode of every omima agent. We don't worship the strong, but we don't ignore their methodology — what's engineerable is already absorbed into the product.

**omima is the carrier of this methodology.** The model is still DeepSeek; the way it's used is omima's:

- **Context organization**: Polaris 1B handles memory retrieval and pure task extraction; the cloud model receives an organized question, not scattered dialogue
- **Toolchain flow**: Xagent's five-step process walks "research → argue → plan → execute → review" end to end; the model doesn't just answer once and stop
- **No paying twice for repetition**: cache-hit lets same-class tasks skip the full inference path from the second time (real ledger §3.6: 5.63B tokens / ¥444.55)

omima doesn't sell models. Models are already first-tier; omima sells **the method that lets most people actually use first-tier models well**. The problem was never how good top closed models are — it's that first-tier capability is already in hand and most people haven't used it.

**Author's lived experience — on-demand is not a slogan, it's daily work**: omima's author subscribes to many services — Anthropic, OpenAI, Grok, Volcano Engine, OpenRouter, LongCat — choosing tools by task type, never idolizing a single strongest model. omima was designed this way: not assuming "which model is strongest" first, but establishing "what task uses what resource" as the working mode, then systematizing it into inference routing. omima's on-demand calling is the engineering of the author's real workflow.

**An honest exploration direction**: multi-agent small-model collaboration can rival a single large model on some tasks (paper-backed) — omima is working toward this; it doesn't conflict with LLM progress, it's another application path. We do not claim the path is fully walked — it's still in progress, but the direction is right: compensate for compute scarcity with methodology.

---

## 3. Technical Architecture: Astral Metro Domain

### 3.1 Architecture overview

```
                    ┌─────────────────────────────┐
                    │   Porphyrion (black-hole node)│
                    │   · 1B Polaris focal point    │
                    │   · sole memory holder        │
                    │   · intra-domain dispatcher   │
                    │   · data enters, never leaves │
                    └──────────┬──────────────────┘
                               │
               ┌───────────────┼───────────────┐
               │               │               │
         Orbit 1 (Green)  Orbit 2 (Blue)  Orbits 3–6
         register         invoke          memory / ironlaw
               │               │           / reply / handoff
               │               │               │
    ┌──────────┴───┐  ┌────────┴────┐  ┌──────┴──────┐
    │ Armory POS   │  │ Strategist  │  │ Scout/Guard/│
    │ tool exec    │  │ POS         │  │ Vault POS   │
    │ Xagent       │  │ 9B / 35B    │  │ search/monitor│
    │ IronLaw exec │  │ or API      │  │ private model│
    │ ECS Shenzhen │  │ MAX host    │  │ ECS HK etc.  │
    └──────────────┘  └─────────────┘  └──────────────┘
```

### 3.2 Porphyrion protocol laws

1. **Polaris uniqueness**: at any moment, exactly one Polaris focal point — □(|Polaris| = 1)
2. **IronLaw domain-wide**: IronLaw covers all star-nodes; outside the domain cannot see inside rules, inside cannot violate them
3. **Memory to the pole**: all persistent memory targets Polaris; non-Polaris star-nodes are stateless executors
4. **Entry requires decree**: new star-nodes join only with Polaris manual approval
5. **Pole transfer is tracked**: Polaris role transfer is a four-step atomic operation (initiate → accept → broadcast → step down)

### 3.3 Six orbits (Porphyrion protocol operations · sys-hooks)

> **sys-hooks** (system hooks): the six primitive operations of the protocol layer, covering all agent-to-agent collaboration patterns (join, invoke, memory, pre-check, reply, handoff). Each hook has a fixed Schema — both a communication contract and training-data ground truth.

| Orbit | Operation | Type |
|-------|-----------|------|
| L₁ Green | `register` | star-node joins, declares capability + IronLaw constraints |
| L₂ Blue | `invoke` | unified call: `tool` (sync) / `task` (async delegation) / `inference` (model routing) |
| L₃ Gold | `memory.*` | intra-domain memory: write/search/forget, three scopes (session/user/grid) |
| L₄ Red | `ironlaw.check` | security pre-check: Galois connection guarantees operation legality |
| L₅ Silver | `reply` | result return: done/failed/streaming chunks |
| L₆ Black | `handoff.*` | focal-point transfer: four-step atomic context migration |

### 3.4 Star-network roles

| Role | Star-node | Duty | Typical hardware |
|------|-----------|------|------------------|
| **Polaris** | focal point | 1B router · sole memory holder · intra-domain dispatch | phone/laptop/desktop |
| **Armory** | arsenal | tool execution · IronLaw enforcement · persistent Vault | ECS Shenzhen 2C4G |
| **Strategist** | strategist | inference routing: edge 35B (local/private) or cloud DeepSeek/LongCat (complex/large) | AMD MAX 395+/400 mini host (product) / ECS+GPU (demo) |
| **Scout** | scout | external search · web_search · web_fetch | ECS Hong Kong (low latency) |
| **Guard** | sentinel | cron tasks · health checks · alerts | ECS any region |
| **Vault** | private vault | private models · local storage · NAS mount | home NAS / local model |

### 3.5 Tool side — Harness-level multi-agent execution engine (Xagent desktop · omima APK mobile · DEMO builds)

The tool side is the user's **harness / orchestration layer**, in two form factors: **Xagent (desktop / headless star-node harness)** — carries the core execution duty of all satellite POS nodes in the star-network; **omima APK (mobile entry)** — issue and observe from anywhere. Both are currently **DEMO builds**, not release-ready engineering. They share the same orchestration layer (IronLaw, tool constraints, five-beat process, experience reuse); only the form factor differs.

An agent is a large model plus tools — that's all. Most harness frameworks define tools narrowly as exec/grep/system calls, focused on workflow distillation and information retrieval; their tool ecosystems revolve around skills, MCP, plugins — everything serving effective data return.

omima's focus differs. omima cares about digital sovereignty and about the harness framework itself. Xagent's understanding of "tool" goes beyond "what can be executed" — through subsystems embedded in the framework, it gives tools deeper meaning:

**IronLaw subsystem**: tools are not naked calls. Every tool call must pass framework-level pre-checks before execution — file paths, command whitelist, network egress, permission boundaries. Violations are blocked at the framework layer, never reaching execution. Tool boundaries are defined by the framework, not by model discretion.

**Memory Tag subsystem**: tool outputs are not one-off. Every tool call's task spec, data schema, output constraints get persistent tags written into the Polaris memory base. The next same-class task hits cached tags first, injecting context directly — reducing repeated-inference token consumption. Tool execution experience accumulates at the framework layer.

**Token consumption mechanism**: framework-level reuse of inference paths directly affects cost. First execution of a task class — full inference path, baseline token cost. Subsequent same-class tasks — tag hit → context pre-injection → shorter inference path → token cost drops 40–60%. This is not prompt-level tuning — it's framework-level execution-path reuse.

This mechanism comes from Reasonix's cache-hit design, ported as-is into Xagent. Its effect is not an estimate — it's a ledger that already happened (see §3.6): cumulative 5.63B tokens for ¥444.55.

**Five-beat process (internalized working method)**: ideate → argue → plan → execute → review. Each step involves one or more agents, producing auditable intermediate artifacts. Multi-agent **serial-stream with parallel steps** — process serial without skipping beats, execution surface can parallelize; no omission, no black box. This is the Loop-engineering default, not a prompt users write each time.

**Six need classes → six-class / 28-task spectrum**: basic capabilities, reasoning & science, dialogue & creation, knowledge & encyclopedia, safety & responsibility, long-context & agents — tool base and evaluation organized by need class for coverage; product algorithms derived from the need spectrum (see `core-thesis.md`).

Xagent does not chase a grab-bag of tool attachments. It pursues a **solid tool base** — boundaries constrained by framework, experience accumulated at framework layer, paths reused by framework: **Harness engineering itself**. Same efficiency design as protocol algorithms, model internalization, hardware staffing — not an external plugin catalog.

### 3.6 Real cost ledger

| Item | Value |
|------|-------|
| Cumulative tokens | 5.63B |
| Actual spend | ¥444.55 |
| Mechanism | cache-hit: repeated reasoning almost free |
| Nature | application-layer ledger, not a GPU score |

---

## 4. Core Innovations

### 4.1 Innovation 1: Porphyrion — the first agent communication protocol with governance primitives

Kang & Diponegoro (2026, arXiv:2606.31498) systematically gap-analyzed five protocols (MCP, A2A, ACP, ANP, ERC-8004) — **all five score zero or near-zero across six governance dimensions.** The paper's conclusion: "Agent-community governance constitutes a missing architectural layer above current interoperability standards."

Porphyrion is the first protocol that directly answers this finding:
- `ironlaw.check` (L₄ orbit) = deliberation + dissent reservation — rule validation before execution
- `node.register` (L₁ orbit) = membership — new nodes join only with Polaris approval
- `handoff.*` (L₆ orbit) = audit/replay — role transfer with full logs

**Implementation status (honest design/implementation split)**: protocol design complete (six-orbit schemas defined); orchestration-layer IronLaw shipped as **IronLaw 4 Gate + Consultation Gate** (Intent / Action / Output / Certify + external API help when local confidence < 0.72) — strategy-A minus: making verifiable governance primitives solid rather than claiming everything.

Compared with existing protocols: MCP has 3 operations (tool/resource/prompt), A2A has 11 methods — Porphyrion's 6 orbits cover a broader semantic space than both combined.

**Protocol lineage & heterogeneous interop**: Porphyrion is not invented from nothing — it evolves the production-proven UnionAgents communication protocol (internal ILS protocol → A2A-standard adaptation → unified OFP semantics). `invoke(mode: tool)` aligns with MCP tool calling, `invoke(mode: task)` aligns with A2A task delegation, `handoff.*` + `reply` cover Agent Client Protocol scenarios; the six sys-hooks let **heterogeneous multi-agent nodes** (different models, hardware, hosts) interoperate in one protocol domain instead of fighting on their own.

### 4.2 Innovation 2: 1B Polaris = the sole memory holder (the "second brain")

**Core insight**: the 1B router (INT4 ~500MB) is the only stateful node in the grid. All large models become stateless inference engines.

```
Traditional agent:
  LLM prompt = task + context + memory + conversation history
  → private data leaves the device

omima:
  1B Polaris → retrieve memory → distill a pure task prompt
  → send to large model (zero context) → infer → return → immediately forget
  → 1B combines with memory → compose final reply
  → the large model never knows "who the user is"
```

**Zero mutual information**: I(MemoryGraph; L₂.payload) = 0. The cloud model can get nothing about user memory from the prompt.

This design directly answers Selective Persistent Memory (arXiv:2607.09493) — selective memory raises task completion from 79% to 96%. The difference: omima centralizes memory in the 1B model, not the application layer. R2V Agent (arXiv:2605.16604) proves small models can route but doesn't touch "small model as sole memory holder."

### 4.3 Innovation 3: protocol spec as training data

EnterpriseLab (2026) shows tool-Schema-generated synthetic trajectories can let an 8B model match GPT-4o — but this concept **has never been applied to the agent communication protocol itself.**

Each of Porphyrion's six orbits has a fixed JSON Schema. From the Schema, infinitely many legal messages can be generated deterministically — as LoRA fine-tuning training data. The protocol spec itself is the training-data source: no manual labeling, no user-data collection. The protocol defines what a correct message is, and therefore what a correct training sample is.

---

## 5. Demo Plan

**Primary form: VOX explainer video** per `demo-storyboard-vox.md` — infographic motion + Chinese voiceover: six needs → three pillars → harness·loop·hardware → one task walkthrough → AMD measured numbers (FP8 +65%, tool-call 8/9). 3–5 min main cut, 90s short available.

### 5.1 VOX narrative arc

1. Six need classes
2. Three pillars: protocol & algorithms · model internalization · five-beat working method (serial-stream)
3. Efficiency engineering three facets: Harness · Loop · hardware
4. One abstract task walkthrough from ideate to review
5. AMD / MI300X numbers & role staffing (infographic cards)

### 5.2 Real data flow inside the system (abstractable for animation)

```
Need positioning (six classes)
  → protocol routing (pillar 1)
  → five-beat serial/parallel (pillar 3)
  → role models + star-node execution (pillar 2 + harness)
  → IronLaw pre-check / review
  → high-satisfaction delivery (auditable artifacts)
```

**Key points**: privacy (memory at focal point), boundaries (DENY), process (no skipped beats), hardware staffing (role-to-silicon) — told graphically in the VOX.

---

## 6. Glossary — the neglected link in the application chain

The AI industry loves coining words. More worth discussing: **which links these words point to, and which links are always ignored.**

**Prompt Engineering**

Industry focus: how to phrase for better model output.
Ignored: the intermediate artifacts at each step — research raw material, argument chains, review check results. Not recorded, not reused, not audited. omima's five-beat process forces every step to keep auditable artifacts.

**Loop**

Industry focus: a while loop that makes the agent retry until success.
Ignored: the loop's boundaries. Who defines "success"? Who backs up when the loop fails? Who owns the intermediate data? omima's IronLaw defines tool boundaries — not "try a few more times," but "some things must never be tried."

**Harness**

Industry focus: connecting tools to the LLM. exec, grep, web_search — as long as it runs.
Ignored: tool behavior constraints, tool execution experience, tool call-path reuse. omima's Xagent embeds three subsystems at harness layer — IronLaw for boundaries, Memory Tag for experience, Token mechanism for reuse. These are what comes after "putting on the harness," which most harness frameworks don't do.

**Skill / MCP / Plugin**

Industry focus: connecting more tools, packaging more capability.
Ignored: governance after connection. A pile of plugins — who can call whom? Where does data go after the call? Two plugins with conflicting permissions? omima's Porphyrion protocol defines six orbits — not "how to connect," but "how to collaborate once connected": membership (who may join), operation pre-check (can it execute), audit replay (who did what).

**In one sentence**: omima doesn't redefine what Prompt Engineering is, how to write a Loop, or how to call MCP. omima defines the part these words don't cover — the neglected link in the application chain. Tool boundaries, experience reuse, governance rules. That is the essence of a harness framework.

---

## 7. Market & Business

### 7.1 Target users

| User group | Pain | omima answer |
|------------|------|--------------|
| Privacy-sensitive | don't want conversations/files uploaded to vendors | data never leaves the device |
| Heavy AI users | seat-based subscription decouples price from usage | cache-hit: repeated reasoning not paid twice |
| Multi-device users | phone/laptop/desktop data fragmented | Astral Metro Domain unified orchestration |
| Developers/power users | need controllable, auditable AI infrastructure | open source + own ECS + auditable |

### 7.2 Competitive landscape

| Dimension | ChatGPT / Claude | Single-agent | omima |
|-----------|-----------------|--------------|-------|
| Privacy model | data to cloud | data to cloud | never leaves device |
| Billing | subscription $10–30/mo·seat | subscription $20/mo | cache-hit: repetition nearly free |
| Agent collaboration | within vendor ecosystem | built-in single | cross-device distributed |
| Hardware binding | none | none | AMD heterogeneous |
| Moat | model capability | model capability | time barrier (memory compounding) |

### 7.3 Business model

- **Open core**: Porphyrion protocol + Xagent MIT open source
- **Value-added services**: one-click ECS satellite POS templates, enterprise grid ops, custom IronLaw rules
- **Hardware binding**: AMD-exclusive experience — millisecond Polaris inference on Ryzen AI NPU

---

## 8. Roadmap

| Phase | Time | Milestone |
|-------|------|-----------|
| **P0** | done | Xagent engine + MCP endpoint + 19 tools deployed (ECS Shenzhen 120.24.227.46) |
| **P1** | during hackathon | Porphyrion protocol stack (six-orbit WebSocket impl) + Polaris 1B router prototype |
| **P2** | +3 months | mobile omima APK (omima-1B router + edge small model + Porphyrion client) + base training pipeline |
| **P3** | +6 months | multi-user grid + ACI 1B-driven + memory system iteration |
| **P4** | +12 months | production Astral Metro Domain + deep AMD hardware adaptation |

---

## 9. Team

**kon** — full-stack architecture + agent system design.
Author of omima / Xagent / Porphyrion protocol. AMD heterogeneous-computing ecosystem researcher.

---

## Appendix A: Technical metrics

| Metric | Value / target | Status |
|--------|----------------|--------|
| 35B-A3B FP8 vs BF16 | ~195 vs ~118 TPS (C=3) | **measured @ MI300X vLLM** |
| tool-call | 8/9 | **measured** |
| omima-35B LoRA serving | ~59–65 TPS (short) | **measured** |
| omima-35B / 9B training | Loss ~0.96 / ~0.79; ~1h11m / ~57min | **measured @ MI300X** |
| 9B CPU GGUF | ~13 t/s, tool-call OK | **measured** |
| Confidence threshold | ~0.72 | **measured/calibrated** |
| Polaris 1B latency | <500ms class (product target) | target |
| L₂ / join / IronLaw latency | see engineering target table | phased |
| Data egress | task description only; memory never leaves focal point | design + demo |

Single source of truth: `00-PACKAGE.md` §3 · `evidence/INDEX.md`.

## Appendix A2: AMD GPU / ROCm optimization (40 points)

**Submission chapter (judges' primary read)**: [`amd-rocm-technical.md`](./amd-rocm-technical.md)
**Evidence index**: [`evidence/INDEX.md`](./evidence/INDEX.md)
**English summary**: [`README.en.md`](./README.en.md)

Focus: local inference · quantifiable speed methods · ROCm ecosystem toolchain. Narrative spine: staffing before tuning; edge + constellation; MI300X main chain, conventional and verifiable.

## Appendix B: Key references

> arXiv IDs as recorded; re-verify when citing.

[1] Kang & Diponegoro (2026). Governance Gaps in Agent Interoperability Protocols. arXiv:2606.31498
[2] Selective Persistent Memory for Agentic LLM Systems. arXiv:2607.09493
[3] R2V Agent: Teaching SLMs When to Ask for Help. arXiv:2605.16604
[4] EnterpriseLab: Full-Stack Platform for Enterprise Agentic Workflows. arXiv:2603.21630
[5] Semantic Consensus: Conflict Detection for Multi-Agent Systems. arXiv:2604.16339
