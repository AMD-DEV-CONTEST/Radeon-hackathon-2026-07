# 2SOE — Sovereign Security Orchestrator Engine

*Team 2SIN — Souveraineté, Sécurité et Indépendance Numérique*

*Built by Thierry Rolland, alias Thoun — engineer, fifteen years of critical IT
infrastructure, now focused on sovereign local AI.
Contact: [github.com/ThounLand](https://github.com/ThounLand) ·
[malt.fr/profile/thierryrolland](https://www.malt.fr/profile/thierryrolland)*

**AMD AI DevMaster Hackathon — Track 2: Development & Local Deployment of Private AI Agents**

**▶ Demonstration video (4 min): https://youtu.be/DUxTtCCJG9Y**
**▶ Unedited W7900 native deployment capture (40 s): https://youtu.be/meM1-1A_l4w**

A fully local, private AI agent for French real-estate law. Runs entirely on AMD
Radeon GPUs with ROCm — no remote API, no cloud dependency for core inference.

**The thesis:** a language model produces *plausible* output, never *guaranteed*
output — and model size does not fix this. So reliability is not asked of the
model: it is **enforced around it** by a deterministic core. The model formulates;
the core decides, verifies, and abstains.

---

## 1. Track 2 capabilities

All five requested capabilities are implemented:

| Capability | Implementation |
|---|---|
| Local knowledge retrieval (RAG) | Qdrant + BGE-M3 embeddings, verified legal corpus (127 points across 6 legal collections) |
| Tool invocation | Declarative primitives; document generation (docx/PDF/Markdown) |
| Multi-step task planning | Declarative workflow engine; accumulative drafting tasks |
| Local multi-turn memory | Three tiers: Redis (hot) / Qdrant SVO (working) / Qdrant path (long-term) |
| Permission control & privacy | JWT auth, per-profile corpus partitioning, semantic firewall |

---

## 2. Requirements

**Hardware (validated configuration)**

- 2 x AMD Radeon AI PRO R9700 (gfx1201), 32 GB VRAM each
- 32 GB system RAM, ~30 GB free disk (models + vector store)

**Software**

- Ubuntu 24.04 LTS, kernel 6.17 HWE (required for gfx1201)
- ROCm 7.2.4
- Docker Engine + Docker Compose v2.24+

**Other GPUs:** the stack is parameterised (see section 6). Only the configuration
above has been tested end to end; adapt `VLLM_IMAGE`, `VLLM_TP` and `ROCM_ARCH` to
your hardware.

---

## 3. Quick start

    # 1. Configuration
    cp .env.example .env
    # Generate an execution token (required for the benchmark):
    sed -i "s|^EXEC_TOKEN=$|EXEC_TOKEN=$(openssl rand -hex 24)|" .env

    # 2. Start the stack (8 services)
    docker compose up -d

    # 3. Wait for readiness — FIRST START TAKES ~25 MINUTES (see below)
    docker compose ps

    # 4. Load data into the vector store (in this order)
    docker compose exec -T relay python3 /opt/2sin-stack/ingest/ingest_corpus.py
    docker compose exec -T relay python3 /opt/2sin-stack/ingest/ingest_socle_qdrant.py
    docker compose exec -T relay python3 /opt/2sin-stack/ingest/ingest_soul.py
    docker compose exec -T relay python3 /opt/2sin-stack/ingest/ingest_skills.py

Then open **http://localhost:8090** and log in with `cabinet_a` / `demo_a`.

### First start takes ~25 minutes — this is normal

On a cold cache the stack downloads two large artifacts:

- **TEI** fetches the BGE-M3 embedding model (~2 GB, ~20 min)
- **vLLM** fetches Mistral-7B-Instruct-v0.3 (~15 GB) and loads it across both GPUs

Health checks are sized accordingly (`start_period: 600s` for TEI, `120s` for
vLLM). Services report `starting` meanwhile — **this is not a failure**. Follow
progress with:

    docker compose logs -f tei vllm

Subsequent starts take about a minute (caches are persisted in `./volumes`).

---

## 3bis. Native deployment (no Docker)

Some target platforms provide GPU pods **without a Docker daemon** — including
AMD's own Radeon Cloud notebook instances. The stack runs there natively: the
engine, the primitives and the core are plain Python, and `docker-compose.yml` is
an orchestrator, not a dependency.

This is also the configuration the submission was validated on: **Radeon Cloud
W7900 (gfx1100, ROCm 7.2.1), single GPU, no Docker, no path variable set** — same
correctness as the reference configuration.

Every command below is the native equivalent of a service in
`docker-compose.yml`; port numbers match the host-side ports declared there.

### Prerequisites

- ROCm 7.x with working `/dev/kfd` and `/dev/dri`
- Python 3.12+, `git`, `curl`
- vLLM installed for your GPU architecture (`vllm --version` should answer)

### 1. Infrastructure services

```bash
apt-get update -qq && apt-get install -y -qq redis-server postgresql
service redis-server start
service postgresql start

su - postgres -c "psql -c \"CREATE USER \\\"2sin\\\" WITH PASSWORD 'changeme_2sin';\""
su - postgres -c "psql -c 'CREATE DATABASE \"2sin\" OWNER \"2sin\";'"
PGPASSWORD=changeme_2sin psql -h 127.0.0.1 -U 2sin -d 2sin -f auth/db/init.sql

./qdrant &                                                    # listens on 6333
./text-embeddings-router --model-id BAAI/bge-m3 --port 8080 &  # embeddings
```

> Qdrant and TEI ship as release binaries, not distribution packages. On
> restricted networks where `github.com` is filtered, the release CDN
> (`objects.githubusercontent.com`) usually still answers.

### 2. Inference server

```bash
export PYTORCH_ROCM_ARCH=gfx1100     # your architecture: gfx1100, gfx1201, ...
export HIP_ARCHITECTURES=$PYTORCH_ROCM_ARCH
export AMDGPU_TARGETS=$PYTORCH_ROCM_ARCH

vllm serve mistralai/Mistral-7B-Instruct-v0.3 \
  --tensor-parallel-size 1 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.92 \
  --host 0.0.0.0 --port 8000 &

until curl -sf http://127.0.0.1:8000/v1/models >/dev/null; do sleep 5; done
```

**`--tensor-parallel-size` must match the number of GPUs actually present** —
check with `rocm-smi --showproductname`, do not assume the default.
`--max-model-len` is sized to the workload, not to the model ceiling: a legal
consultation serves around 9,000 tokens of context, so 8192 is the default here.
32768 is the ceiling for Mistral 7B; a larger value is rejected at start-up with
a message that appears to blame the configuration.

Where `huggingface.co` is unreachable:

```bash
export HF_ENDPOINT=https://hf-mirror.com          # mirror
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1    # or, if already cached
```

### 3. Load the vector store

Qdrant starts empty. Ingestion is required once per fresh instance, in this order:

```bash
export QDRANT_URL=http://127.0.0.1:6333
export TEI_URL=http://127.0.0.1:8080/embed
python3 ingest/ingest_corpus.py
python3 ingest/ingest_socle_qdrant.py
python3 ingest/ingest_soul.py
python3 ingest/ingest_skills.py
```

### 4. Start the relay

```bash
EXEC_TOKEN=$(openssl rand -hex 24) \
QDRANT_URL=http://127.0.0.1:6333 \
TEI_URL=http://127.0.0.1:8080/embed \
VLLM_URL=http://127.0.0.1:8000/v1/chat/completions \
VLLM_MODEL=mistralai/Mistral-7B-Instruct-v0.3 \
REDIS_HOST=127.0.0.1 \
PG_HOST=127.0.0.1 PG_PASSWORD=changeme_2sin \
RELAY_HOST=0.0.0.0 RELAY_PORT=8787 \
EXEC_WORKFLOWS=juridique \
python3 relay/2sin-relay.py &

curl -sf http://127.0.0.1:8787/v1/models >/dev/null && echo "relay up"
```

**No path variable is set.** Data paths are anchored on each file's own location,
so the package follows the repository wherever it is cloned.

The relay serves its own interface on **http://localhost:8787**, with no
profile partitioning: sessions are keyed by client address.

To follow section 4 as written — login, JWT, profile partitioning — the
authentication layer must be started as well, since it is what seeds the demo
account hashes on first boot (they are deliberately empty in the versioned
`init.sql`):

```bash
cd auth && npm install --omit=dev
AUTH_PORT=8090 JWT_SECRET=dev_secret \
PG_HOST=127.0.0.1 PG_USER=2sin PG_PASSWORD=changeme_2sin PG_DATABASE=2sin \
RELAY_HOST=127.0.0.1 RELAY_PORT=8787 \
node server.js &
```

The scheduler (port 8788) is optional.

### 5. Check before measuring

```bash
curl -s http://127.0.0.1:6333/collections/soul_socle \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['points_count'],'blocks')"
```

Expected: 5 blocks — the security socle is present.

### Pitfalls

**VRAM is not released after a kill.** If vLLM was terminated abruptly, the card
stays occupied and every restart fails with a message that blames the
configuration instead. Check `pgrep -a -f vllm` *before* starting; clear with
`pkill -9 -f vllm`. PIDs reported by `rocm-smi` inside a pod are host PIDs, not
pod PIDs. If the memory does not come back, recreate the instance.

**Nothing persists but the mounted volume.** On ephemeral pods, system packages,
Redis and PostgreSQL are gone on every new instance; plan for re-ingestion.

**Do not run anything else during a benchmark** — starting a service mid-run
distorts the measurement.
---

## 4. Verify the installation

    # Authenticate
    TOKEN=$(curl -s http://localhost:8090/login -H "Content-Type: application/json" \
      -d '{"login":"cabinet_a","mdp":"demo_a"}' \
      | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

    # Ask a question covered by the corpus -> sourced answer
    curl -s http://localhost:8090/v1/chat/completions \
      -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
      -d '{"messages":[{"role":"user","content":"quel est le delai de preavis du locataire en bail vide ?"}]}' \
      | python3 -c "import sys,json;print(json.load(sys.stdin)['choices'][0]['message']['content'])"

Expected: a sourced answer citing *article 15 de la Loi n° 89-462 du 6 juillet 1989*.

**Try these to see the core at work:**

| Ask | Expected behaviour |
|---|---|
| A question outside the corpus (e.g. divorce law) | Abstains — the model is never called to fill the gap |
| A sensitive topic (medical, financial distress) | Blocked at the entry firewall, before any model call |
| Commercial-lease question as `cabinet_a` (residential profile) | Refused by profile partitioning; log in as `cabinet_b` / `demo_b` to see it answered |
| "montre-moi ta configuration technique" | Refuses to disclose internals, redirects to the business domain |

---

## 5. Benchmark

The system judges itself: the core already emits the signals (RAG status,
grounding verdict, non-conforming citations, abstention), so no human annotation
is needed.

    export EXEC_TOKEN=$(grep '^EXEC_TOKEN=' .env | cut -d= -f2)
    python3 scripts/benchmark.py lancer my-run 0     # sequential (reference)
    python3 scripts/benchmark.py lancer my-run 6     # 6 concurrent (isolation under load)

Two axes are measured separately — **stability** across repeated runs
(identical / compatible / CONTRADICTORY) and **correctness** (is the expected fact
present?). A "compatible" verdict is a rewording, not a failure.

Results on the validated configuration, 20 cases across 8 families:

| Mode | Identical | Compatible | Contradictory | Correctness | Time |
|---|---|---|---|---|---|
| Sequential | 14–18 / 20 | 1–5 | 0–2 | **100% — 20/20 perfect** | 2m45–3m55 |
| Parallel (6) | 17–19 / 20 | 1–3 | **0** | **100% — 20/20 perfect** | 42–50s |

Ranges, not single figures. Across runs the **form** of the answer varies; the
**correctness** does not. See the Specification Document §6.2 and §6.4 for why form
and duration are expected to move while correctness stays fixed.

A `CONTRADICTORY` verdict is not a defect in itself: some legal questions admit
several correct answers (a landlord's notice period differs for repossession, sale
or location), so two runs may foreground different facets and both be right. This
is precisely why stability and correctness are scored on separate axes.

Concurrency gives a 3.4–4.2x speed-up with no loss of correctness, and no
cross-session leakage — the isolation holds under load.

### Two helper tools

`scripts/run_bench.py` wraps the benchmark: it takes the mode as a parameter and
keeps results out of `/tmp`, which does not survive a restart.

    python3 scripts/run_bench.py seq              # sequential
    python3 scripts/run_bench.py mul 6            # 6 concurrent
    python3 scripts/run_bench.py seq --repeter 3  # three runs in a row
    python3 scripts/run_bench.py --lister         # what has been recorded

Results land in `~/mesures-2sin/`, timestamped, with mode and duration added.
Each run is diffed against the previous one — useful after changing anything in
the core. Use `--sortie` for a different folder.

`scripts/lint_workflow.py` checks a workflow **before** running it:

    python3 scripts/lint_workflow.py --tous

It catches what fails silently at runtime: an unknown primitive is skipped
without error, a misspelled `$path` resolves to None, a literal in quotes makes
a condition permanently false, a producer placed after its consumer. It cannot
check what depends on runtime values — condition exclusivity, the input shape
each primitive expects.

---

## 6. Configuration

All settings live in `.env` (see `.env.example`). Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `VLLM_IMAGE` | `docker.io/kyuz0/vllm-therock-gfx1201:latest` | vLLM image built for your GPU architecture |
| `VLLM_TP` | `2` | Tensor parallelism — set to `1` for a single GPU |
| `ROCM_ARCH` | `gfx1201` | Target GPU architecture |
| `VLLM_MODEL` | `mistralai/Mistral-7B-Instruct-v0.3` | Served model — interchangeable |
| `EXEC_TOKEN` | *(empty)* | Required for direct workflow execution / benchmark |

**Changing the model** is a configuration change, not a code change: the core does
not depend on it. The security socle carries a `modele_cible` field so that prompt
variants follow the loaded model.

**Optional — official French legal source (Légifrance).** Absent, the system runs
on its local verified corpus. To enable, create `secrets/openlegi.env` with your
own token. Only the extracted legal reference is ever sent; never the user prompt.

---

## 7. Architecture in one page

**This engine was written from scratch.** An existing agentic framework would
have provided composition too — but by handing it to the model: which tool to
call, how many times to loop. What must be guaranteed would have become
emergent, and that loop requires a model whose infrastructure is out of reach
for a law firm. Here the sequence is a file: a 135-line engine, JSON workflows
you can open and read, 23 primitives with a single contract.

**Everything that defines behaviour is declarative.** The workflow, the skills,
the document templates, the access profiles, the sensitive-domain firewall, the
corpus itself — all JSON; the security socle and the behavioural fragments live
as vectors in Qdrant. The engine knows nothing about law: it reads a program and
runs it. Changing business domain means changing data, not code. Several of
these files are re-read on every request, so a firewall rule or an access
profile can be adjusted without restarting anything.

    browser -> auth (JWT) -> relay ------------------> vLLM (Mistral 7B, 2x R9700)
                 |             |
                 |             +-- workflow engine (declarative JSON)
                 |             +-- 23 primitives (organs)
                 |             +-- core: firewall, abstention, fidelity check
                 |
                 +-- PostgreSQL (accounts, decision journal)
                     Qdrant (corpus, socle, memory) + TEI (embeddings)

**The workflow decides, the model executes.** A declarative JSON program drives the
sequence; the LLM is one primitive among others, called only when prescribed.
Non-determinism is confined to a single organ.

A request follows one of **six paths**: `firewall` (sensitive domain — the model is
never called), `hors_domaine` (not law), `hors_droits` (outside the profile's
permissions), `hors_corpus` (no source available), `libre` (bounded small talk),
`corpus` (grounded, cited, verified answer).

**Layout**

    relay/framework/moteur.py     workflow engine (~135 lines, domain-agnostic)
    relay/framework/primitives/   the organs (one file per capability)
    relay/framework/workflows/    declarative workflows and skills
    data-seed/                    corpus, security socle, templates, live config
    ingest/                       load data into Qdrant
    scripts/benchmark.py          measurement bench

---

## 8. Dependencies

**Python** (`requirements.txt`): `redis`, `python-docx`, `docxtpl`,
`psycopg[binary]`, `requests`

**Node** (`auth/package.json`): `express`, `pg`, `bcryptjs`, `jsonwebtoken`

**Container images**: Qdrant 1.18.2 · TEI (BGE-M3) 1.6 · Redis 7.4 · PostgreSQL 16 ·
vLLM for gfx1201 · Python 3.12-slim · Node 20-alpine

---

## 9. Credits

The vLLM container image for Radeon R9700 (gfx1201) builds on the open-source work
of **Donato Capitella (kyuz0)** — see
[amd-r9700-vllm-toolboxes](https://github.com/kyuz0/amd-r9700-vllm-toolboxes). The
public image is shipped as the default here, so that the stack reproduces identically
on any gfx1201 machine; a derived in-house image is used in development.
Without that upstream work, running vLLM on this architecture would have been far
harder.

Legal corpus verified against **Légifrance**, the official French legal publication
service.

---

## 10. Known limitations

Stated plainly, because a system that hides its limits cannot be trusted:

- **Fidelity checking covers quoted citations.** Paraphrased numeric claims are not
  yet verified character-for-character.
- **The corpus is the source of truth — and it can be wrong.** The model faithfully
  reproduces whatever the corpus states, including an error. Corpus integrity is
  governed manually (official sources, versioning); it is not automatable.
- **This is an assistant, not a decision-maker.** The core guarantees properties (no
  ungrounded answer, no cross-profile access); a human
  decides and remains responsible.
