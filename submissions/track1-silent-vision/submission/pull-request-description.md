# Track 1, Jixin Fang, Silent Vision

## Project

Silent Vision recognizes a personalized catalog of fixed phrases from a 2-5
second silent camera clip. It is a closed-set visual classifier, not
open-vocabulary lipreading. Its current catalog is one four-phrase bilingual
catalog: Chinese `你好，请帮我打开灯` and `你吃饭了吗？`, and English
`Hello, please turn on the light.` and `Have you eaten?`, mapped to `LIGHT_ON`
and `CHAT_OTHER`. The user selects the language before recording; it is not
inferred from visual input. `UNKNOWN` is produced only by heuristic rejection.

PyAV and MediaPipe decode the video, find one face, align it, and create a 96 x
96 grayscale mouth sequence on CPU. The fixed-phrase Torch model trains and runs
on AMD Radeon through ROCm. It uses 16 x 16 appearance and adjacent-frame motion
maps, two depthwise-separable temporal blocks, attentive pooling, a normalized
embedding, and a dynamic phrase head.

The ROCm-only Torch classifier calculates a selected-language softmax among the
enabled phrases for the user-selected language. An accepted prediction must pass
both the checkpoint probability threshold and the predicted phrase's
centroid-distance threshold. Exact text and intent then come from the checkpoint
catalog. Rejected clips return `UNKNOWN` with no matched phrase text and no
executable action. Top-1 margin is diagnostic only.

The repository returns structured decisions. It does not control a physical
device or content-creation application. The command boundary can be integrated
with a creator workflow, but that integration is not claimed here.

## Submission materials

- [x] English source, dependency list, setup, training, evaluation, and startup
  guide: `submissions/track1-silent-vision/README.md`
- [x] Versioned phrase catalog:
  `submissions/track1-silent-vision/command/phrase_catalog.json`
- [x] Project profile source and generated PDF:
  `submissions/track1-silent-vision/docs/submission/project-profile-source.md`
  and
  `submissions/track1-silent-vision/submission/Silent-Vision-Project-Profile.pdf`
- [x] Poster source, PDF, and PNG:
  `submissions/track1-silent-vision/docs/submission/poster-copy.md`,
  `submissions/track1-silent-vision/submission/Silent-Vision-Poster.pdf`, and
  `submissions/track1-silent-vision/submission/Silent-Vision-Poster.png`
- [x] Demo script and evidence checklist:
  `submissions/track1-silent-vision/submission/demo-video-script.md`
- [x] Demo video: `submissions/track1-silent-vision/submission/Silent-Vision-Demo-720p.mp4`
- [x] Source repository: <https://github.com/fangjixin/silent-vision>

## Evidence status

The official Radeon run completed on 2026-08-06. Its evidentiary inventory
contains 73 known clips and 15 unrelated clips across Chinese and English. The
frozen untouched evaluation produced:

- phrase top-1 accuracy: 12/12 (100%);
- mapped-intent accuracy: 12/12 (100%);
- known acceptance: 5/12 (41.7%);
- accepted known phrase accuracy: 5/5 (100%);
- unrelated rejection: 9/10 (90%); and
- accepted precision including the one unrelated false accept: 5/6 (83.3%).

Training and evaluation used PyTorch 2.9.1, ROCm HIP 7.2, `cuda:0`, and one
`gfx1100` AMD GPU. The model has 46,405 parameters. Checkpoint SHA-256:
`c70d28ae2ed84ee4b2cb0811ebff18870e7b905c1540bc96a782656fba385453`.
The inventory, checkpoint, and final report are all evidentiary and their lineage
was verified. A real WebSocket replay also returned the exact Chinese light-on
phrase with the Torch backend on `cuda:0` and `action: execute`.

These are personalized, same-speaker fixed-phrase results, not evidence of
open-vocabulary lipreading or cross-speaker generalization. The recorded demo
URL remains pending.
