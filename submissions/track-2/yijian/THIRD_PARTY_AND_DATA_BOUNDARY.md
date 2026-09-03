# Third-Party and Data Boundary

## Models and engines

- Qwen3-14B is used at the fixed upstream revision recorded in the evidence manifest. Base weights are not redistributed here.
- KataGo 1.16.5 and its official b40 network provide Go analysis. Binaries and weights are not redistributed in this submission folder.
- vLLM, PyTorch, Transformers, FastAPI, and other libraries remain under their respective upstream licenses.

## Creator-authorized data

The creator corpus is authorized for non-commercial research and competition demonstration. The project records creator, video URL, time range, authorization ID, attribution, source binding, human approval, and KataGo artifact hash. This is not described as unrestricted or commercial authorization.

Raw video/audio, full transcripts, reviewer comments, authorization screenshots, training text, and the resulting adapter are private and excluded from the public snapshot.

## Public-domain and reference-only sources

Only registered public-domain excerpts are training-eligible. Project explanation surrounding those excerpts is labelled `project-original+public-domain`. Modern official or educational web pages are reference-only unless their licenses expressly allow reuse: the project independently rebuilds positions and writes original explanations, while recording URL, access time, hash, and policy.

## Private user data

Private SGFs, reports, sessions, and memory databases remain local. Memory is disabled by default, written only through an explicit confirmation endpoint, and individually or fully deletable. Private game text is not used for training.

## Public snapshot exclusions

The snapshot generator rejects caches, logs, hidden directories, large files, credentials, private keys, personal Windows paths, databases, media, model files, adapters, restricted workspaces, and sealed data. It retains source code, tests, schemas, aggregate counts, hash manifests, and synthetic examples.
