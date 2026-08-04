# Judge Quickstart

This guide targets the verified Radeon environment: Python `3.12.3`, ROCm
`7.2.1`, HIP `7.2.53211-e1a6bc5663`, and a detected `AMD Radeon Graphics`
device (`gfx1100`, device ID `0x744b`, 96 compute units, `51522830336` VRAM
bytes). The product string is reproduced verbatim; no retail GPU model is
inferred.

## 1. Verify the hardware boundary

```bash
python3 --version
hipconfig --version
rocminfo | sed -n '1,80p'
rocm-smi --showproductname --showmeminfo vram --showuse
```

Confirm the versions and detected values above, then save the command output with
the final evidence bundle.

## 2. Start the local model

```bash
cd submissions/track2-radeonstay
: "${LLAMA_BIN:?Export LLAMA_BIN as the frozen ROCm llama-server binary}"
: "${MODEL_FILE:?Export MODEL_FILE as the frozen local GGUF path}"
test "$(sha256sum "$LLAMA_BIN" | awk '{print $1}')" = \
  "926e2297d7144a59182ba9d37de877ec972a0cf8d1b697baa82277b3066c45c6"
test "$(sha256sum "$MODEL_FILE" | awk '{print $1}')" = \
  "4fe53b148b46f9b88830e2a3055c5b15c3a4d1e3ddc9a1384a108d8b9d59f043"
LLAMA_SERVER="$LLAMA_BIN" \
MODEL_PATH="$MODEL_FILE" \
MODEL_ALIAS="${RADEONSTAY_MODEL_NAME:-qwen3.6-35b-a3b-q6k}" \
EVIDENCE_RUN_ID=radeon-target-baseline-001 \
scripts/serve_model.sh \
  > evaluation/results/radeon-target-baseline-001-llama-server.log 2>&1
```

`MODEL_FILE` is
`unsloth/Qwen3.6-35B-A3B-GGUF@a483e9e6cbd595906af30beda3187c2663a1118c/Qwen3.6-35B-A3B-UD-Q6_K.gguf`
(Apache-2.0). `LLAMA_BIN` is built from llama.cpp commit
`0b14b87d7c20cb753b94b96854dd7b45306fc696`.

The service must bind to `127.0.0.1:8000` for the private judge path. Use a
second terminal with
`tail -f evaluation/results/radeon-target-baseline-001-llama-server.log` if
live logs are needed; stopping the launcher writes the evidence end marker to
that file.

## 3. Start RadeonStay

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
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
scripts/serve_app.sh
```

The generated 48-byte secrets are different, remain only in the ignored `.env`,
and are required even for loopback-only use. Open `http://127.0.0.1:7860`.

## 4. Run the judge journey

Use the seeded guest and the prefilled Chinese prompt in the UI. On every new
session, the UI computes two exact future dates as local `today+30` and
`today+32`; the Agent is intentionally forbidden from inventing a stay window.
The visible prompt therefore follows this runtime-generated form:

> 我计划从 <today+30> 入住到 <today+32> 退房，23:30 到店，带一名六岁
> 儿童，有严重花生过敏，需要安静房和机场接送。请引用酒店政策，查询
> 可用房和准确报价，并在我确认前只预览保留房间。

Check the policy citations, plan, room inventory and quote. Review and confirm
the pending reservation hold. The UI prefills the next editable transfer request
with the returned booking ID; submit it, then opt in to preference memory. Each
write remains a separate preview and confirmation. For example:

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
