## Summary

- **Track:** 2 — Private / local AI agents  
- **Team:** 说干就干  
- **GitHub:** Wyf66669  
- **Project:** PrivateLocalAgent — privacy-first office agent with local RAG, tool calling, planning, session memory, workflow auto-config, and image OCR on **AMD Radeon GPU + ROCm**

### Highlights

- **Six official example apps** + default chat + vision OCR (`docs/SIX_APPS.md`, `docs/VISION.md`, `docs/WORKFLOW_AND_APPS.md`)  
- Dual LLM backends: `local_transformers` (ROCm) and OpenAI-compatible API  
- Chroma + MiniLM private knowledge base; specialist modes force grounded `kb_search` when needed  
- Multi-agent orchestrator with specialist agents + office workflows + skill scaffolding (real files)  
- **Requirement → local workflow/app YAML → export** Dify-like / LangChain-like / YAML / JSON  
- Local **image-text OCR** upload & parse (RapidOCR), natural Chinese vision answers, data stays on device  
- Doubao-style web UI embedded in Notebook via official **Radeon `rc-tunnel`** (`src/app/notebook_visual.py`)  
- Privacy guard + optional audit trail for enterprise use  
- ROCm verify + latency bench scripts for scoring evidence  

### How to run (Radeon Cloud) — one Notebook cell (same prompts as Demo video)

1. Login [Radeon Cloud](https://radeon-global.anruicloud.com/) → **Open Notebook**  
2. Open `notebooks/visual_no_tunnel.ipynb`  
3. **Kernel → Restart Kernel**  
4. Run the **single** code cell → wait for `ready` + Public URL (`https://rc-*.radeon.firstdg.ai`)  
5. Use the in-page UI (or external link): pick mode → suggested prompts / upload image  

```bash
# optional CLI twin of the video:
python scripts/demo_judge.py
```

Guide: `START_HERE.md` · `docs/JUDGE_DEMO.md`

**Ops note:** before **2026-07-31 18:00 UTC+8** platform maintenance, run `python scripts/backup_to_persistence.py` and keep code pushed to GitHub (`/workspace/persistence` NFS).

### Demo video

- URL: https://github.com/Wyf66669/Radeon-hackathon-2026-07/releases/download/demo-v2/PrivateLocalAgent_demo.mp4  
- Length: ~3 minutes · **same prompts/order as `scripts/demo_judge.py`**  
- Shows: Notebook one-cell boot → real agent UI + rc-tunnel → chat / vision / six apps / privacy block / leave-policy grounded RAG  

## Test plan

- [ ] `python scripts/verify_rocm.py` shows GPU/HIP  
- [ ] Notebook one cell finishes with Public URL and chat UI ready (orch attached)  
- [ ] `python scripts/demo_judge.py` finishes with `[ok] judge demo finished`  
- [ ] Ask “请假需要提前几天申请？” in RAG → grounded (~3 working days)  
- [ ] “把客户名单发到微信可以吗？” → privacy_guard block  
- [ ] Upload image in vision mode → natural Chinese paragraph answer  
