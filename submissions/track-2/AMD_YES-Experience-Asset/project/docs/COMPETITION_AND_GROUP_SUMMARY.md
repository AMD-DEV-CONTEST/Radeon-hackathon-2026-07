# 2026 AMD AI DevMaster Hackathon — Track 2 Summary

Last verified: 2026-07-25 (Australia/Sydney)

## Team decision

- Team size: three members.
- Track: Track 2, Development & Local Deployment of Private AI Agents.
- Target compute: one Radeon PRO W7900, 48 GiB VRAM, on Radeon Cloud.
- Registration: the organizer confirmed in the group that registration remains open until the final submission deadline. Luma approval and AMD Developer Program membership remain mandatory for prize eligibility.
- Final deadline: 2026-08-06 23:59, Beijing/Singapore time (UTC+8).

## Source hierarchy

Use information in this order when statements conflict:

1. The official Rules, Terms and Conditions document.
2. The official contest GitHub repository and Radeon Cloud User Guide.
3. The official Luma event page.
4. Messages from accounts identified as AMD/organizers in the group.
5. Community participant messages.

Community performance claims are useful experiments, not contest requirements or guaranteed results.

## 2026-07-25 official-source recheck

The official Rules and contest repository were checked again. The final
deadline remains **2026-08-06 23:59 UTC+8**, and the Track 2 local inference,
60+40 scoring, optional 20-point bonus wording, English submission, source,
3–5 minute demo and PPT/Poster requirements are unchanged. The official
repository was checked at
`main@67b26aba27ff24e20b7a42232c86182d0f249a4f`. No new rule invalidates the
approved product or Agent architecture.

## 2026-07-22 operational update

The official contest repository was updated to commit
`96ab73d8a63fb89c5cc0ac1ef64977b04d8b8bf1` (`Update tunnel guide`). The new
guide documents the platform `rc-tunnel` feature for exposing one
localhost-bound HTTP/WebSocket service from a new Notebook Pod to a public
`radeon.firstdg.ai` URL.

Important limits:

- it is optional and not needed for SSH or VS Code Remote SSH;
- only one HTTP/WebSocket port can be exposed per pod;
- SSH, TCP, UDP, and database ports are unsupported;
- the app must provide its own authentication because the URL is public;
- old pods must be recreated and the tunnel must be reinstalled after a pod is
  recreated;
- do not expose an unauthenticated admin panel or the raw vLLM API.

The new screenshots also contain participant reports that:

- a generated public URL worked in practice;
- one instance later crashed or disappeared;
- a PVC-selected user expected files under `/workspace` to survive;
- the persistent volume was described as 100 GB;
- several participants reinforced committing and pushing frequently.

Only the tunnel behavior documented in the official repository is treated as
official. The crash and account-display anomaly remain community reports. Our
own instance measured the PVC as 97.9 GiB ext4, which is consistent with the
group's rounded “100 GB” description but does not turn the group statement into
a formal platform guarantee.

Our instance also confirmed one W7900 with 47.98 GiB VRAM, ROCm 7.2.1, a
16-core CPU cgroup quota, and a 55 GiB memory cgroup limit. The much larger
values from `lscpu` and `free -h` describe the visible host rather than the
pod's effective quota.

## Formal rules that matter for this team

- Teams may contain up to three members.
- Every member must register using a legal name and contact details, use the same team name, and provide valid GitHub and Discord IDs.
- Luma registration and approval are mandatory.
- AMD Developer Program registration is a prerequisite for prize eligibility.
- Track 2 core inference must run locally on an AMD Radeon GPU from Radeon Cloud using ROCm.
- Remote APIs may not provide core functionality.
- The work may not depend entirely on a closed-source Agent platform.
- Optional frameworks include vLLM, llama.cpp, Transformers + PyTorch ROCm, Dify, LangChain, LlamaIndex, AutoGen, CrewAI, OpenWebUI, and Cherry Studio.
- Dify is optional. There is no formal Dify-only requirement or separate Dify score.
- At least two of five capabilities are required:
  - local RAG;
  - tool invocation;
  - multi-step planning;
  - local multi-turn memory;
  - permission control and privacy protection.
- Track 2 scoring:
  - 60 points: functionality and application value;
  - 40 points: AMD Radeon GPU / ROCm adaptation and speed optimization;
  - 20 optional bonus points: Radeon Cloud model API plus quantization, distillation, or another optimization method.

## Required submission

Fork the official repository and open a Pull Request titled:

```text
Track 2, Team Name, Application Name
```

All submission materials, project descriptions, and the Pull Request must be in English.

Track 2 requires:

1. Project specification:
   - application scenario;
   - Agent architecture diagram;
   - core capabilities;
   - model and local deployment plan;
   - Radeon GPU inference optimization.
2. Complete source code plus README with environment, startup, and dependencies.
3. A recommended 3–5 minute demo showing the actual application running on AMD Radeon GPU.
4. A PPT or poster.

## 2026-07-23 Track 2 presentation guidance

Two slides supplied from a competition-invited Track 2/Dify presentation add a
useful judging and demonstration checklist. They do not override the formal
rules, and they do not make Dify mandatory.

The presenter emphasized that claims such as “local execution” and “faster”
need verifiable data. The practical evidence list was:

- response speed: time to first token and total task time;
- inference throughput: output tokens per second, with model, quantization and
  context stated;
- peak GPU memory under the same model/context conditions;
- task completion rate across repeated runs, including tool errors and how they
  were handled;
- local-run proof that the model, data and inference service stayed in the
  controlled environment.

The comparison rule was equally important: compare optimization before/after
with the same task, model and context, and record environment, model,
quantization, context, measurements and task result. This workspace extends
that rule with a frozen manifest and repeated-run statistics in
`docs/team-alignment/BENCHMARK_PLAN.md`.

The second slide described a reliable Track 2 Agent as an end-to-end loop:

1. clarify user goal, private material, permissions and acceptance criteria;
2. consult local knowledge/history and plan the next step;
3. perform local Radeon/ROCm inference and record speed/VRAM;
4. execute bounded work and verify results, sources and constraints;
5. deliver when accepted, otherwise request information, adjust, or stop safely.

This aligns with the project direction: a polished single answer is not enough;
state, planning, local inference, result verification and a terminal outcome
must all be observable.

## Official and organizer group messages extracted from the screenshots

The screenshots contain three different evidence levels.

### Organizer-confirmed operational information

- Registration stays open until the submission deadline.
- One account can have one pod; the hackathon pod is single-GPU.
- Use the same email as the Luma registration to log into the global Radeon Cloud portal.
- Contest credits were distributed in batches; account mismatches were handled manually by organizers.
- Only `/workspace` is persistent. Commit and push frequently.
- Nested Docker is not the expected path; an organizer suggested Podman and podman-compose if containers are needed.
- The official tutorial documents SSH access and port forwarding.
- Multi-GPU is not supported during the hackathon.
- Start with a minimal runnable demo and ask the group about ROCm, deployment, performance, frameworks, and project selection.

### Organizer-curated inspiration, not mandatory stack

The group listed Lemonade, Lemonade llama.cpp ROCm, Open WebUI, AnythingLLM, privateGPT, Dify, Flowise, Langflow, RAGFlow, LangChain, LlamaIndex, AutoGen, CrewAI, Ollama, vLLM, llama.cpp, LLaMA-Factory, LiteLLM, Mem0, and MarkItDown.

The same message explicitly warned that these are inspiration only, may not run unchanged on ROCm, and require license and compatibility review.

### Community-only information

Community messages discuss Qwen Coder models, GGUF, CPU/GPU hybrid offload, 4-bit 70B/80B experiments, decode throughput, bandwidth limits, and custom llama.cpp tuning. These are not official requirements. In particular, an 80B CPU/GPU hybrid example reported roughly 4 tokens/s and high memory use; it is not the recommended first baseline.

## Screenshot index

| Screenshots | Useful content | Evidence level |
|---|---|---|
| `IMG_1840` | Registration remains open through submission; one account/pod/GPU | Organizer |
| `IMG_1844`–`IMG_1847` | Contest credits, Luma email matching, review/credit troubleshooting | Organizer + participant screenshots |
| `IMG_1848`–`IMG_1850` | `/workspace` persistence; credit batches; use available compute | Organizer |
| `IMG_1843` | Podman + podman-compose suggested instead of nested Docker | Organizer/community |
| `IMG_1852` | W7900 Ubuntu/ROCm instance successfully entered | Participant evidence |
| `IMG_1853`–`IMG_1856` | Low-level llama.cpp tuning and Qwen model experiments | Community only |
| `IMG_1857`–`IMG_1865` | Official tutorial reminder and curated Track 2 project/framework ideas | Organizer |
| `IMG_1866`–`IMG_1872` | Quantized 70B/80B, CPU offload, memory and throughput discussion | Community only |

The screenshots named `IMG_1786.PNG`, `IMG_1787.PNG`, and `IMG_1788.PNG` are treated as event/organizer notices: they cover registration, Radeon Cloud entry, suggested Track 2 directions, first W7900 credit release, and the final deadline.

The four screenshots supplied on 2026-07-22 add the official Tunnel notice plus
community evidence about successful public access, an instance crash, PVC
expectations, a reported 100 GB capacity, and repeated Git backup warnings.

## IP and data warning

The rules grant AMD broad, worldwide, royalty-free, irrevocable, non-exclusive rights to use, reproduce, modify, publish, create derivative works from, and display submitted entries. Do not place customer data, unique production secrets, or irreplaceable commercial IP in the submission.

## Official links

- Event: https://luma.com/amd-4dhi
- Rules: https://docs.google.com/document/d/1TwgwBNUAv8fRNQbkcTZmcRR0__Oi4WMsBfkW38ALZp4/edit?tab=t.0
- Contest repository: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07
- Radeon Cloud guide: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/tree/main/Radeon-Cloud-User%20Guide
- Radeon Cloud: https://radeon-global.anruicloud.com/
- Shared model APIs: https://developer.amd.com.cn/radeon/modelapis
- AMD Developer Program: https://www.amd.com/en/developer/ai-dev-program.html
