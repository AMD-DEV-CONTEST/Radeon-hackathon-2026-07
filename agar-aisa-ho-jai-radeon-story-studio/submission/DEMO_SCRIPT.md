# 3–5 Minute Demo Script — Agar Aisa Ho Jai — Radeon Story Studio

## 0:00–0:20 — Problem and result

Show the accepted safe-charger lesson card. Explain that polished generation is not enough if the depicted action is wrong, so every output remains unaccepted until review passes.

## 0:20–0:50 — Repository and architecture

Show the public README, sealed manifest, two local Radeon workflows, and the privacy boundary.

## 0:50–1:20 — Radeon/ROCm proof

On the Radeon machine show:

```bash
python - <<'PY_DEMO'
import torch
print('torch:', torch.__version__)
print('hip:', torch.version.hip)
print('available:', torch.cuda.is_available())
print('device:', torch.cuda.get_device_name(0))
print((torch.ones(4, device='cuda:0') * 2).cpu())
PY_DEMO
```

Also show `rocminfo`/`rocm-smi` output and the `gfx1100` device.

## 1:20–2:10 — SDXL Story Studio

Validate the manifest, prepare/inspect the sealed package, then show the recorded run report and candidate timings. Explain the modular content classes and why incomplete action scenes were rejected.

## 2:10–3:00 — Qwen Storyboard Factory

Show the local vLLM endpoint, run the factory command, and show structured plan, textual safety review, generated contact sheet, and animatic. Display measured token throughput.

## 3:00–3:40 — Evidence and acceptance

Show SHA-256 evidence, runtime identity, component dtypes, peak memory, rejected-candidate reasons, and accepted output report.

## 3:40–4:10 — Practical value and close

Explain how a creator can replace the lesson transcript while retaining deterministic constraints, local Radeon inference, and explicit review. State the current limitation: textual safety review is not a complete multimodal frame review.

## Recording checklist

- Keep the terminal text readable.
- Show actual commands and final outputs, not only slides.
- Include Radeon/ROCm identity in the recording.
- Show both successful output and one fail-closed rejection.
- Keep total duration between 3 and 5 minutes.
- Add English narration or English subtitles.
