# Third-Party Licenses & Attribution

XAI Local Agent Studio is a secondary-development project built on top of multiple
open-source components and community practices. This file documents known
dependencies and borrowed implementations to ensure proper attribution.

## Frontend dependencies (installed via npm at build time, not shipped in repo)

All under permissive licenses (MIT / ISC):

- React 18, React-DOM — MIT (Meta)
- Vite 5 — MIT (Evan You / Vite team)
- Tailwind CSS 4 — MIT (Tailwind Labs)
- React Flow (reactflow) — MIT (webkid)
- Framer Motion — MIT (Framer)
- lucide-react — ISC (Lucide)
- Mermaid — MIT (KnisterPeter / mermaid-js)
- date-fns — MIT (date-fns)
- react-big-calendar / rbc-recurrence — MIT
- zustand — MIT (pmndrs)
- prismjs — MIT (Lea Verou)

These are declared in `frontend/package.json` and resolved at build time.

## Backend (Python, zero runtime dependencies)

The backend (`server_xai.py`, `core/`) runs on the Python standard library only.
Some algorithmic patterns and reference implementations were adapted from public
open-source projects and community discussions. Where specific files were
directly derived from a published source, the original license header should be
preserved in the file. Maintainers are responsible for verifying and updating
attribution as the project evolves.

## Model weights

Inference uses models served via Ollama (e.g. Qwen2.5, Qwen2.5-Coder under
Apache 2.0 from Alibaba). Model weights are NOT included in this repository and
must be pulled at runtime per the provider's license.

## Note on Hackathon Submission

This project is submitted to the AMD AI DevMaster Hackathon (Track 2: Private AI
Agent Development & Local Deployment). Source code is published as required by
the contest rules. All third-party components retain their original licenses.
