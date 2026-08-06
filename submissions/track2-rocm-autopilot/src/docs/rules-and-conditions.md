# Rules & Conditions: Track 2 extraction (filled 2026-08-05)

> Sources: official R&C Google Doc ("2026 AMD AI DevMaster Radeon GPU Hackathon",
> https://docs.google.com/document/d/1TwgwBNUAv8fRNQbkcTZmcRR0__Oi4WMsBfkW38ALZp4/edit),
> the Luma event page (https://luma.com/amd-4dhi), and the submission repo README
> (https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07). Quotes are verbatim.

## Deadline

- Final submission: **August 6, 2026, 5:59 PM CEST** (Beijing UTC+8: 11:59 PM; US Pacific: 8:59 AM).

## Deliverables (Track 2, all four required, all in English)

1. **Project Specification Document**: application scenarios · agent architecture diagram · introduction to core capabilities · model introduction & local deployment plan · "Optimization description for inference speed on AMD Radeon GPU". (PDF is required for Track 1's document; Track 2 does not specify a format, PDF is the safe choice.)
2. **Project Source Code**: complete source code repository · README with environment configuration, startup guide and dependency list.
3. **Demo Video**: recommended 3 to 5 minutes · "Demonstrate the actual operation process" · "The actual execution performance on an AMD Radeon GPU, from command line/GUI to the final result. (fluidity and functional completeness)".
4. **Supplementary Materials (Choose One)**: PPT / Poster.

## Submission mechanics

- Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` and open a PR containing the submission.
- PR title (repo README, verbatim): "Track x, Team name, your application name".
- Fallback (repo README, verbatim): "Team name was an optional field on the Luma registration form. If you did not fill in a team name when you registered, please use your own name instead".
- "All submission materials, project descriptions, and Pull Requests should be submitted in English."
- PRs are public.

## Judging criteria (Track 2, verbatim structure): total 120 points

The Luma page summarizes 60 + 40 = 100; the governing R&C adds a 20-point optional bonus.

1. **Functional Completeness of AI Agent (60)**
   - "Clear task positioning and creative application scenarios: 20 points"
   - "Complete core capabilities including task decomposition, tool invocation, RAG and memory management: 20 points"
   - "Smooth multi-turn interaction experience: 20 points"
2. **Adaptation & Optimization for AMD Radeon GPU / ROCm (40)**
   - "Core inference running on AMD Radeon GPU: 20 points"
   - "Targeted optimization for inference speed: 20 points"
3. **Optional bonus points (20)**
   - "Core inference running Using Radeon cloud model API with quantization or distillation or other optimization methods." (sic)

## Functional gate (Track 2)

"The work shall implement at least 2 of the following 5 capabilities (more capabilities will earn extra credits)": Local knowledge retrieval (RAG) · Tool invocation · Multi-step task planning · Local multi-turn memory · Clear permission control & privacy protection mechanism.

## Tech-stack constraints (Track 2)

- "Must run on AMD Radeon GPU of Radeon cloud + ROCm software stack".
- "Core inference processes shall be executed locally on AMD Radeon GPU; remote APIs are not allowed for core functions".
- "It is not allowed to depend entirely on closed-source Agent platforms to implement core features".
- Optional frameworks: "vLLM / llama.cpp (adapted for AMD Radeon GPU)", "Transformers + PyTorch ROCm", agent frameworks "any you love but have to be neutral framework".

## Eligibility (prize-gating)

- Luma registration AND approval mandatory; AMD AI Developer Program membership is a pre-requisite ("Participants who are not registered members of the AMD AI Developer Program will not be eligible to receive prize money, even if their submission is selected as a winning project").
- Individuals or teams of up to three (3); "All team members must register using their legal name and contact details, and provide the same team name".
- 18+; valid Discord ID and valid GitHub ID required; sanctioned-country and AMD-employee exclusions apply.
- Winner notification by email within 7 days of judging; tax/eligibility forms (W-9 / W-8 BEN) may be required within 10 days; team prizes split evenly; winners list published on the AMD Discord.

## Pre-existing code / IP

- No clause prohibiting pre-existing or own prior code was found in the R&C. Our approach stays: openly declare the lineage from our own Apache-2.0 gemma-autopilot in the README and PR.
- IP grant (verbatim, key extract): participants give AMD "a royalty-free, irrevocable, non-exclusive worldwide license to use, reproduce, modify, publish, create derivative works from, and display the entry [...] All Entries become the property of AMD, and none will be returned."
- The license granted to AMD is explicitly **non-exclusive**: participants keep the right to license their own code as they wish.

## License requirements for submissions

- None stated. The R&C requires open-source components for core functions (no closed-source model/agent-platform dependence) but imposes no license on the participant's own code.

## Prizes (per track)

1st: $5,000 · 2nd: $3,500 · 3rd: $1,500 (USD).

## Radeon Cloud

- Access and usage: "Radeon-Cloud-User Guide/README.md" in the submission repo. No credit rules or instance limits appear in the R&C itself.

## Support

Discord: https://discord.gg/zt9caur5B3 · Email: ai_dev_contests@amd.com
