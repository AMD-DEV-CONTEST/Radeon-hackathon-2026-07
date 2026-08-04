# Judge Quickstart

This guide targets a prepared AMD Radeon/ROCm environment. Exact image, ROCm,
model, and llama.cpp revisions will be pinned after P0 hardware validation.

## 1. Verify the hardware boundary

```bash
rocminfo | sed -n '1,80p'
rocm-smi --showproductname --showmeminfo vram --showuse
```

Save the command output with the final evidence bundle.

## 2. Start the local model

```bash
cd submissions/track2-radeonstay
LLAMA_SERVER=/workspace/llama.cpp/build/bin/llama-server \
MODEL_PATH=/models/qwen3.6-35b-a3b-q6k.gguf \
EVIDENCE_RUN_ID=radeon-w7900-baseline-001 \
scripts/serve_model.sh > evaluation/results/llama-server.log 2>&1
```

The service must bind to `127.0.0.1:8000` for the private judge path. Use a
second terminal with `tail -f evaluation/results/llama-server.log` if live logs
are needed; stopping the launcher writes the evidence end marker to that file.

## 3. Start RadeonStay

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
python - <<'PY'
from pathlib import Path
import secrets

path = Path(".env")
text = path.read_text(encoding="utf-8")
replacements = {
    "replace-with-a-random-local-secret": secrets.token_urlsafe(48),
    "replace-with-a-different-random-local-secret": secrets.token_urlsafe(48),
}
for placeholder, secret in replacements.items():
    if placeholder not in text:
        raise SystemExit(f"Missing expected placeholder: {placeholder}")
    text = text.replace(placeholder, secret, 1)
path.write_text(text, encoding="utf-8")
PY
radeonstay
```

The generated 48-byte secrets are different, remain only in the ignored `.env`,
and are required even for loopback-only use. Open `http://127.0.0.1:7860`.

## 4. Run the judge journey

Use the seeded guest and the prefilled Chinese prompt in the UI. It includes two
exact future dates because the Agent is intentionally forbidden from inventing
a stay window:

> 我计划从 2030-09-10 入住到 2030-09-12 退房，23:30 到店，带一名六岁
> 儿童，有严重花生过敏，需要安静房和机场接送。请引用酒店政策，查询
> 可用房和准确报价，并在我确认前只预览保留房间。

Check the policy citations, plan, room inventory and quote. Review and confirm
the pending reservation hold. Copy the returned booking ID into the next
request, then create the transfer ticket and opt in to preference memory. Each
write is confirmed separately. For example:

> For booking RSV-..., request pickup from Terminal 1 for synthetic flight
> RS123 arriving 22:45, for one adult and one six-year-old needing a child
> seat. Enable local memory so I can separately confirm saving quiet_room as
> high_floor.

Finally switch to the unauthorized identity without changing the current
session and verify that the session is refused. In a fresh Mallory session,
created with **New session**, `my bookings` may return only Mallory's own records.

## 5. Inspect evidence

The UI exposes tool receipts and audit IDs. Raw benchmark artifacts live under
`evaluation/results/`; no summary number is valid without a matching raw file.
For an evidence run, use the same run ID in the model log, Agent benchmark and
ROCm monitor, then create the hash-bound bundle described in
`docs/evaluation-plan.md`.
