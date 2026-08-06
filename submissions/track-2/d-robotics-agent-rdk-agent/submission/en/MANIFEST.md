# Track 2 Delivery Manifest - RDK Agent

Validated on **2026-08-06**.

## Primary deliverables

| Deliverable | File | SHA-256 |
| --- | --- | --- |
| Project specification | [RDK_Agent_Project_Specification.pdf](deliverables/RDK_Agent_Project_Specification.pdf) | `f77ff42aa2ebd58a015664dfe1e5d135d334c11607c511d53fafc09a7e4949ac` |
| Pitch deck | [RDK_Agent_Track2_Pitch_Deck.pptx](deliverables/RDK_Agent_Track2_Pitch_Deck.pptx) | `807e1711d3e14d536b5704f8510120a1c1a614cebb9902e945d4026b570461ce` |
| Demo video | [Bilibili primary](https://www.bilibili.com/video/BV1t3up6iEhy/) · [Baidu Cloud MP4 backup](https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd) | `0cba7eec725a4c8d7e76a3b762c56ce1c96cc8edd9321daf0a2342c0cd0a0a4f` |

## Submission sources

- [Submission index](README.md)
- [Project specification source](PROJECT_SPECIFICATION.md)
- [Evaluator reproducibility guide](REPRODUCIBILITY.md)
- [AMD Radeon/ROCm deployment and evidence guide](AMD_RADEON_ROCM.md)
- [Verification log](evidence/verification-2026-08-05.md)
- [Demo video placeholder and shot list](VIDEO.md)
- [Pull request copy](PR_DESCRIPTION.md)
- [Final submission checklist](SUBMISSION_CHECKLIST.md)

## Validation result

- The PDF is a readable, unencrypted 12-page A4 document with no forms or JavaScript.
- The PPTX archive is structurally valid, contains 12 slides and speaker-note source blocks, and passed rendered overflow inspection.
- All local Markdown links resolve.
- The public-facing submission sources contain no detected common credential pattern, private tunnel URL, or board-private IP address.
- The editable SVG diagrams are valid XML.
- The benchmark utility and example JSON configuration pass syntax validation.
- The local demo master is 3:07.2, 1920x1080, H.264/AAC, and 174,000,121 bytes; its duration satisfies the 3-5 minute requirement.
- The Bilibili primary page and Baidu Cloud MP4 backup were both externally reachable on 2026-08-06; the 165.9 MiB local master is excluded from ordinary Git.

## Owner-supplied items still required

1. Replace the team or participant name placeholders.
2. Attach redacted AMD Radeon GPU, ROCm, vLLM, model precision, and baseline-versus-tuned benchmark evidence.
3. Review the worktree, then explicitly approve commit and publication.
