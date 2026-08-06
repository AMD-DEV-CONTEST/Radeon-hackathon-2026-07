# AMD Radeon AI Hackathon - Track 2 submission checklist

- [x] Local-first private agent architecture
- [x] FastAPI orchestration and Next.js user experience
- [x] Local model adapter boundaries: ROCm/HIP, Qwen2.5-VL, BGE, FAISS, PaddleOCR
- [x] Project ZIP generation and downloadable artifacts
- [x] GPU telemetry and benchmark contract
- [x] Architecture, API, local-AI, deployment, test, benchmark, and demo documentation
- [x] Specification PDF and 10-slide deck in `submission/`

## Pull request commands

```bash
git init
git add .
git commit -m "Track 2, <Team Name>, Decompile"
git remote add origin <fork-url>
git push -u origin main
gh pr create --title "Track 2, <Team Name>, Decompile" --body-file SUBMISSION.md
```

Suggested PR summary: "Decompile is a private, ROCm-ready AI agent system that turns a YouTube URL into a complete software engineering package. It includes local orchestration, evidence extraction adapters, generated repositories, GPU telemetry, reproducible benchmarks, and judge-ready documentation."
