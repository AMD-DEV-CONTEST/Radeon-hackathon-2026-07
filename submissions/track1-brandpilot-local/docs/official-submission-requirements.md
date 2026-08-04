# Official submission requirements

Verified on 2026-08-04 from first-party sources. The Rules and Conditions are
treated as governing when another source is less specific.

## Sources

| Source | First-party status | What was verified |
|---|---|---|
| [Official Luma event](https://luma.com/amd-4dhi) | Event page presented by AMD AI Marketing | Schedule, Track 1 scope and scoring, registration prerequisites, official repository, support channel, and Rules link |
| [Rules and Conditions](https://docs.google.com/document/d/1TwgwBNUAv8fRNQbkcTZmcRR0__Oi4WMsBfkW38ALZp4/edit?tab=t.0) | Governing document linked by Luma | Eligibility, required technology, judging, deliverables, submission route, IP, conduct, and legal terms |
| [Official upstream README](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/README.md) | Official submission repository | Fork-and-PR workflow, English-language requirement, PR title convention, and Track 1 deliverables |
| [AMD/Hugging Face announcement](https://huggingface.co/blog/LeRobot-worldwide-hackathon/amd-ai-devmaster) | Announcement linked to the official registration page | Schedule, eligibility notice, Track 1 scope/scoring, prizes, support, and Rules link |
| Official registration email | Private first-party message; not reproduced | One team member's Luma registration approval is confirmed |
| Official Discord invite | Official link from Luma/Rules | Invite resolves to AMD Developer Community; pinned guidance was not accessible because this Chrome profile has not joined the server |

No official submission template, sample project directory, page limit, slide
limit, required branch name, required commit format, or external form was found
in the first-party sources above. The official repository currently contains
its README, the Radeon Cloud User Guide, and supporting guide assets only.

## Mandatory requirements

| Requirement | Exact official requirement | Format / filename | Status for BrandPilot Local |
|---|---|---|---|
| Registration | Luma approval and AMD AI Developer Program membership are prerequisites for prize eligibility. Every team member must register with legal name/contact details and the same team name. Valid Discord and GitHub IDs are required. | Private registration records | One member's approval confirmed. Aqeela Urooj's approval, common registered team name, and both Developer Program memberships are not independently visible in this account. |
| Team size | Individual or team of up to three members; participants must meet age and eligibility rules. | Team information in registration/submission | Two named members, within the limit. |
| Track | Track 1 must deliver a practical multimodal content creation tool with at least one eligible creation task. | Track 1 | Image-to-image generation/editing is implemented and verified on Radeon. |
| Radeon/ROCm | The work must run on AMD Radeon GPU from Radeon Cloud, adopt ROCm, and be deployable/demonstrable in the designated AMD environment. At least one key inference process must run locally on AMD Radeon; the core function cannot rely solely on a closed-source online API. | Evidence in repository/profile/video | Real SDXL img2img and authenticated FastAPI loopback generation are verified on Radeon/ROCm. |
| Demonstrable form | At least one of Web UI, desktop app, plugin, CLI plus demo workflow, or another valid form. | Web UI | Next.js Web UI plus FastAPI backend. |
| Project Profile | Include project background, target users/scenarios, system architecture, model/algorithm, and AMD Radeon/ROCm adaptation. | PDF; no official filename or page limit | `submission/BrandPilot-Local-Project-Profile.pdf` |
| Source code | Complete source repository with README covering environment configuration, startup guide, and dependencies. | Public fork and PR; English | This repository and official-fork package. |
| Submission route | Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` and open a pull request containing the submission. Preserve official repository content. | GitHub PR | Required; no separate external form found. |
| Language | Materials, descriptions, and PR must be in English. | English | Package is English. |
| PR title | Official README: `Track x, Team name, your application name`. When no registered team name exists, use the participant's name. | PR title | Registered team name is not independently verified; do not guess it. |
| Deadline | August 6, 2026, 11:59 PM Beijing/Singapore time (UTC+8). | GitHub PR by deadline | Verified consistently on Luma, Rules, and announcement. |

## Track 1 judging

Total: 100 points.

- Functional completeness and application value: 80 points.
  - Complete input-processing-output workflow: 40.
  - Innovative and interesting creation scenarios: 20.
  - Practical application and social value: 20.
- Operational performance on AMD Radeon GPU: 20 points.
  - Clear, stable, and diverse tool output: 20.

The shorter Luma wording groups the first 80 points as functional
completeness, practical value, and innovation. It is consistent with the more
detailed governing breakdown above.

## Recommended or elective materials

| Item | Official treatment | Package decision |
|---|---|---|
| Demo video | Recommended duration 3-5 minutes; show actual operation and actual AMD Radeon execution performance from command/GUI to result | A complete recording package is provided. Publication/URL remains a user action. |
| Supplementary material | Choose one: PPT or poster highlighting creative scenarios and practical value | Editable PPTX plus PDF export are provided. |
| Live deployment | Not required by any verified source | `Not required / local-first prototype`. No public deployment is claimed. |
| Poster | Accepted as an alternative to PPT | Not used because a presentation is supplied. |

## Licensing and submission terms

- Open-source models are permitted; LoRA, ControlNet, lightweight inference,
  and distilled models are allowed but not required.
- The core function may not rely solely on closed-source online APIs.
- Entry material must satisfy the Rules' content restrictions.
- The Rules grant AMD a broad royalty-free, irrevocable, non-exclusive,
  worldwide license to use and adapt entry material for stated purposes and
  state that entries will not be returned.
- Personal information is processed under AMD's Privacy Notice.
- No first-party source requires a specific application-source license, but
  project/model/dependency/asset rights must be accurately disclosed.

## Verification gaps and conflict handling

- The authenticated Luma page and approval email confirm one member's approved
  registration. Aqeela Urooj's separate approval is not visible and is not
  claimed.
- The registered team name is not visible. It must be confirmed before the
  official PR title is finalized because the Rules require the same team name
  for all members.
- The official Discord invite is valid, but pinned messages were not inspected
  because joining the server would create an external account side effect.
- No external submission form was located. The verified submission mechanism
  is the official GitHub fork and pull request.
- No live URL is required. The stricter reproducibility and evidence standard
  in the Rules is used instead.
