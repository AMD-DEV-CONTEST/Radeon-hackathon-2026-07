# Radeon Cloud Run Guide (Track 2)

## ⚠ Platform maintenance (backup before Friday)

**Deadline: 2026-07-31 (Fri) 18:00 UTC+8** — platform release / maintenance window.

Before then, on every cloud instance:

```bash
cd /workspace/Radeon-hackathon-2026-07
export PLA_DATA_ROOT=/workspace/persistence/PrivateLocalAgent
export HF_HOME=/workspace/persistence/huggingface
export HF_ENDPOINT=https://hf-mirror.com
python scripts/backup_to_persistence.py
# also push code (required — do not keep a single copy on the VM)
git status
git push origin track2-private-local-agent
```

Checklist:

1. Mutable data under **`/workspace/persistence`** (NFS PVC)
2. Code **pushed** to GitHub (`Wyf66669/Radeon-hackathon-2026-07`)
3. Demo video already on Release `demo-v2` (extra copy)
4. Optional: download a zip of `persistence/PrivateLocalAgent` to your laptop

---

## Persistent storage (important)

Official durable directory:

```text
/workspace/persistence
```

PrivateLocalAgent automatically uses:

```text
/workspace/persistence/PrivateLocalAgent/   # vector store, memory, uploads, workflows, exports
/workspace/persistence/huggingface/        # recommended HF_HOME for models
```

`data/sample_docs/` stays in the git checkout (seed knowledge).  
If you previously saved models/KB under `/workspace/Radeon-hackathon-2026-07/data`, migrate once:

```bash
cd /workspace/Radeon-hackathon-2026-07
export PLA_DATA_ROOT=/workspace/persistence/PrivateLocalAgent
export HF_HOME=/workspace/persistence/huggingface
export HF_ENDPOINT=https://hf-mirror.com
python scripts/migrate_to_persistence.py
python scripts/backup_to_persistence.py
```

Add the three `export` lines to every new terminal session (or put them in `~/.bashrc`).

---

## Primary demo (recommended, no tunnel)

JupyterLab notebook UI — no `rc-tunnel`, no `/proxy`:

```bash
cd /workspace/Radeon-hackathon-2026-07
git pull origin track2-private-local-agent
export PLA_DATA_ROOT=/workspace/persistence/PrivateLocalAgent
export HF_HOME=/workspace/persistence/huggingface
export HF_ENDPOINT=https://hf-mirror.com
```

1. Open `notebooks/private_agent_demo.ipynb`
2. **Kernel → Restart Kernel**
3. Run the **single** code cell
4. Wait for `ready` + chat panel → click **发送**

Optional: expand KB to ~10k related FAQs first:

```bash
python scripts/generate_kb_faqs.py --n 10000
python scripts/rebuild_kb.py
```

## CLI demo (stable fallback for video)

```bash
cd /workspace/Radeon-hackathon-2026-07
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PLA_DATA_ROOT=/workspace/persistence/PrivateLocalAgent
export HF_HOME=/workspace/persistence/huggingface
export HF_ENDPOINT=https://hf-mirror.com
python scripts/migrate_to_persistence.py

python scripts/verify_rocm.py
python scripts/ingest_sample.py
python scripts/demo_cli.py
```

Or one-shot:

```bash
python scripts/bootstrap.py
```

## Optional HTTP / Gradio (needs tunnel or proxy)

These are **optional**. On this platform, `/proxy/PORT` may 404 and `rc-tunnel` may timeout.

```bash
# HTTP demo
export HTTP_PORT=7900
python scripts/web_http_demo.py
# then: rc-tunnel expose --port 7900

# Gradio
export GRADIO_SERVER_NAME=127.0.0.1
export GRADIO_SERVER_PORT=7880
python app.py
```

## Certificates (AMD official)

Successful valid submissions qualify for a **Certificate of Completion**.  
Gold / Silver / Bronze / Excellent certificates are awarded by final review.

## Save credits

Profile → **Destroy Instance** when finished recording.  
Durable files under `/workspace/persistence` survive instance destroy (PVC).
