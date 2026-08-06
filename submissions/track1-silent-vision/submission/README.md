# Silent Vision - Track 1 Submission Index

Applicant: Jixin Fang

Pull request title: `Track 1, Jixin Fang, Silent Vision`

Source repository: <https://github.com/fangjixin/silent-vision>

Silent Vision is a personalized fixed-phrase visual classifier with one
four-phrase bilingual catalog: Chinese `你好，请帮我打开灯` and `你吃饭了吗？`, plus
English `Hello, please turn on the light.` and `Have you eaten?`. The user
selects the language before recording; the application does not infer language
from the clip. Its ROCm-only Torch classifier uses a selected-language softmax,
then returns exact catalog text and a mapped intent only when the probability and
phrase-centroid distance gates pass. Otherwise it returns heuristic `UNKNOWN`.
It is not open-vocabulary lipreading.

| Requirement | Repository path | Status |
| --- | --- | --- |
| Environment, dependencies, and startup guide | [`../README.md`](../README.md) | Complete |
| AMD Radeon / ROCm runbook | [`../docs/runbooks/amd-real-mode.md`](../docs/runbooks/amd-real-mode.md) | Complete |
| Phrase catalog | [`../command/phrase_catalog.json`](../command/phrase_catalog.json) | Complete |
| Project profile PDF | [`Silent-Vision-Project-Profile.pdf`](Silent-Vision-Project-Profile.pdf) | Complete |
| Project profile source | [`../docs/submission/project-profile-source.md`](../docs/submission/project-profile-source.md) | Complete |
| Poster PDF | [`Silent-Vision-Poster.pdf`](Silent-Vision-Poster.pdf) | Complete |
| Poster PNG | [`Silent-Vision-Poster.png`](Silent-Vision-Poster.png) | Complete |
| Poster source copy | [`../docs/submission/poster-copy.md`](../docs/submission/poster-copy.md) | Complete |
| Demo script and shot checklist | [`demo-video-script.md`](demo-video-script.md) | Ready for recording |
| Demo video | [`Silent-Vision-Demo-720p.mp4`](Silent-Vision-Demo-720p.mp4) | Included |
| Pull request description | [`pull-request-description.md`](pull-request-description.md) | Ready; demo link pending |

The source, catalog, documentation, and generated assets are present. The
official bilingual Radeon run and frozen final evaluation completed on
2026-08-06 with evidentiary lineage verified. The untouched final partitions
produced 12/12 phrase top-1 accuracy, 5/12 known acceptance, and 9/10 unrelated
rejection. These are personalized, same-speaker fixed-phrase results. The demo
The 720p demo video is included in this submission directory.

Recordings, checkpoints, and private reports are intentionally excluded from the
public contest bundle.
