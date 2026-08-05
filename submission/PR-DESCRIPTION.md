# Pull Request 模板（提交用）

## Title（全英文，赛制格式）

```text
Track 2, kon, omima
```

（官方格式：`Track x, Team name, your application name`；Track 2 = Development & Local Deployment of Private AI Agents。Luma 未填 Team name，按官方规则用注册者本人姓名 **kon**。）

---

## Body（粘贴到 PR）

```markdown
## Track / Application

- **Track**: Agentic AI (Track 2)
- **Application**: **omima** — Astral Metro Domain (edge + constellation personal agent network)
- **Team**: kon (Luma registered name; no team name filled)

## One sentence

omima is a personal agent network where a 1B Polaris holds memory and routes work, 9B/35B role models run where the job fits, and star-nodes (Xagent, DEMO build) scale on cheap CPU hosts — all three models post-trained and validated on **AMD MI300X (ROCm)** using AMD's pre-contest compute (not the product's runtime configuration).

## What we built

- **Mode**: Edge sovereignty + constellation of stateless star-nodes (not a single mega-model chat box).
- **Model roster**: 1B router/memory · 9B worker · 35B strategist — staffing, not shopping.
- **Runtime**: Xagent harness (**DEMO build**; IronLaw, tools, memory tags) + Gateway (register / events / replay).  
- **Clients**: Xagent (desktop, DEMO) · omima APK (mobile, DEMO) — demonstration builds, not release-ready.
- **AMD main chain (MI300X)**:
  - 35B-A3B FP8 vs BF16: **~195 vs ~118 tok/s (C=3), +65%**, tool-calling **8/9**
  - omima-35B / omima-9B LoRA on MI300X; weights on ModelScope
  - 9B GGUF on CPU: **~13 t/s** tool-call path verified
- **Stack**: ROCm · vLLM · PEFT LoRA · llama.cpp · ModelScope

## Documents in this submission

| Doc | Content |
|-----|---------|
| `README` (this repo) | English overview |
| `docs/main-paper.en.md` | Full technical paper (**English**) |
| `docs/amd-rocm-technical.md` | AMD GPU / ROCm scoring narrative + evidence |
| `docs/pitch-deck.md` | 10-slide outline |
| `docs/demo-script.md` | demo narration for live walkthrough |
| `docs/demo-storyboard-vox.md` | VOX storyboard (production master) |
| `docs/evidence/` | Logs, ModelScope links, metric definitions |

## Demo

**VOX explainer video** (90s, silent motion infographic) per `demo-storyboard-vox.md`: six needs → three pillars → harness·loop·hardware → one task walkthrough → AMD measured numbers (FP8 +65%, tool-call 8/9). File: `evidence/media/omima-vox-90s.mp4`.

## Hardware / reproducibility

- Post-training & primary inference evidence: **AMD Instinct MI300X** (ModelScope contest Notebooks) — **pre-contest compute granted by AMD**; not an omima product configuration (too specialized for ordinary users). Product runs on consumer-class hardware.
- Product placement (mode design): Ryzen AI laptop (9B), MAX-class unified-memory mini PC (35B) — design target; measured GPU chain is MI300X (training/validation)
- Models: `kooooon/omima-1B`, `kooooon/omima-35B`, `kooooon/omima-9B` on ModelScope

## Honest boundaries

- Consumer AMD SKUs not claimed as fully measured in this contest window
- MTP / KV-cache / AITER ablation not claimed as completed score items
- Full multi-10k-sample second-round LoRA is data-ready; first-round job LoRA is what shipped weights prove

## License / contact

- Registered name (Luma): kon
- Core open components: see repository LICENSE notes
```

---

## 检查后提交

- [ ] README.en 数字与 `00-PACKAGE.md` 第三节一致  
- [ ] 无个人 API key / 私钥进入 PR  
- [ ] 安装包为干净演示版  
- [x] 演示视频 = **VOX 动画已交付**（evidence/media/omima-vox-90s.mp4，2026-08-05）
- [ ] 远端 Gitea / 本地 submission 已同步  
