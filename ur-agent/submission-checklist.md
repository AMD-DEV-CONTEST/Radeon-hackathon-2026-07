# UR-Agent Submission Checklist

## 1. Basic information

| Field | Value |
| :--- | :--- |
| Track | Track 2: Development & Local Deployment of Private AI Agents |
| Application name | UR-Agent (Uni-Resource Agent) |
| Applicant | qiancy |
| AMD Developer Program No. | 00000657 |
| GitHub | https://github.com/qiancy/ur-agent |
| Source license | MIT |
| Production demo website | https://rc-e2369faa1fa45132.radeon.firstdg.ai |
| Local demo service | http://127.0.0.1:5173 |
| Submission method | Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`, add the submission materials, and open a Pull Request |
| Suggested PR title | `Track 2, qiancy, UR-Agent (Uni-Resource Agent)` |
| Final deadline | August 6, 2026, 11:59 PM Beijing/Singapore time (UTC+8), which is August 7, 2026, 00:59 Japan time |

## 2. Recommended submission package structure

```text
ur-agent/
  README.md
  submission-checklist.md
  submission-checklist_cn.md
  ProjectSpecificationDocument/
    project-specification.md
    project-specification_cn.md
  ProjectSourceCode/
    README.md
  DemoVideo/
    storyboard.md
    storyboard_cn.md
    video-link.md
    video-link_cn.md
  SupplementaryMaterials/
    PPT/
      outline.md
      outline_cn.md
      UR-Agent-Hackathon-2026.pdf
```

## 3. Required deliverables

| Status | Material | Deliverable | Checkpoint |
| :--- | :--- | :--- | :--- |
| To confirm | Eligibility | Luma registration, AMD Developer Program, GitHub ID, Discord ID | Submit as qiancy, Developer No. 00000657 |
| In progress | Project source code | GitHub repository: `https://github.com/qiancy/ur-agent` | Source code pushed; README includes environment configuration, startup guide, and dependency list; MIT license included |
| Drafted | Project Specification Document | `ProjectSpecificationDocument/project-specification.md` | Covers application scenarios, Agent architecture diagram, core capabilities, model/local deployment, and AMD Radeon GPU inference speed optimization |
| To produce | PPT | `SupplementaryMaterials/PPT/UR-Agent-Hackathon-2026.pdf` or `.pptx` | 6 to 8 slides; highlights scenario, value, architecture, ROCm local inference, and demo results |
| To record | Demo Video | `DemoVideo/video-link.md` | 3 to 5 minutes; recorded via Tencent Meeting; shows command-line or GUI workflow and actual AMD Radeon GPU execution |
| Drafted | Storyboard and voice-over script | `DemoVideo/storyboard.md` | Can be used for recording and TTS narration |
| To add | Performance data | Add to the specification and PPT | Record model, quantization, VRAM usage, tokens/s, first-token latency, and typical end-to-end task time |
| To confirm | PR description | Pull Request body | Include project summary, material links, source link, runtime instructions, demo website, and video link |

## 4. Track 2 capability coverage

| Requirement | UR-Agent coverage | Before final submission |
| :--- | :--- | :--- |
| Local Knowledge Retrieval (RAG) | Isolated knowledge base per organization/context space, with knowledge insertion and retrieval | Show one knowledge retrieval workflow in the video |
| Tool Calling | Agent calls resource, knowledge, people, finance, and Seller tools | Show at least one multi-tool task |
| Multi-Step Task Planning | LangChain Agent decomposes natural language requests into tool sequences | Keep the execution flow visible in the demo |
| Local Multi-Turn Memory | Conversation context is retained across turns in the same session | Show at least two consecutive turns |
| Permission Control & Privacy | JWT carries `puid` and `ouid`; tools are scoped by user and organization context | Show that data does not leak after switching spaces |
| AMD Radeon GPU local inference | llama.cpp ROCm serves a local OpenAI-compatible endpoint on AMD Radeon GPU | Show `rocm-smi` or model server logs |
| Inference speed optimization | GGUF quantization, GPU offload, context trimming, vector indexing, and scoped tool results | Add measured performance numbers |

## 5. Execution plan

| Date | Goal | Tasks |
| :--- | :--- | :--- |
| 2026-08-03 | Submission skeleton | Finish the project specification, checklist, video script, and PPT outline |
| 2026-08-04 | Source and runtime closure | Push `ur-agent` to GitHub; complete README, LICENSE, startup scripts; verify local inference, backend, and frontend |
| 2026-08-05 | Recording and metrics | Record a 3 to 5 minute Tencent Meeting demo; collect AMD Radeon GPU performance numbers; fill the specification and PPT |
| 2026-08-06 | Final submission | Prepare English materials; export PPT PDF; confirm video access; open the Pull Request |

## 6. Pre-PR checklist

- [ ] `https://github.com/qiancy/ur-agent` is public and contains the final source code.
- [ ] The source repository root includes an MIT `LICENSE`.
- [ ] The source repository README includes dependencies, environment variables, startup commands, and test commands.
- [ ] The contest fork includes `ur-agent/README.md`.
- [ ] The contest fork includes the English Project Specification Document.
- [ ] The contest fork includes a PPT or poster, preferably exported as PDF.
- [ ] The contest fork includes an accessible demo video link.
- [ ] The demo website link is included: `https://rc-e2369faa1fa45132.radeon.firstdg.ai`.
- [ ] The video does not expose private keys, tokens, database passwords, internal accounts, or sensitive data.
- [ ] The video shows AMD Radeon GPU / ROCm execution evidence.
- [ ] The video shows at least two Track 2 capabilities; recommended: RAG, tool calling, multi-step planning, memory, and permission isolation.
- [ ] The PR title is `Track 2, qiancy, UR-Agent (Uni-Resource Agent)`.
- [ ] The PR description includes the application name, applicant information, source link, demo website, video link, PPT link, and runtime notes.

## 7. Remaining risks and open items

- Performance data must come from the actual AMD Radeon GPU + ROCm environment. Do not replace final measurements with estimates.
- If the complete source code is not pushed to GitHub before submission, reviewers may not be able to reproduce the project.
- The demo video should include both startup/runtime evidence and the GUI workflow, instead of only static output screenshots.
