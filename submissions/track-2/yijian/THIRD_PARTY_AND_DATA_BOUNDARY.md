# Third-Party and Data Boundary

## Included

- Public source code required to run the YIJIAN agent demo.
- Environment templates with placeholder values only.
- Public benchmark descriptions and reproducible commands.
- A product screenshot that contains no credentials or private training records.
- Third-party license notices for redistributed libraries and assets.

## Excluded from this public submission

- KataGo and Qwen model weights.
- Private or user-imported SGF/GIB records.
- SQLite databases and local feedback logs.
- Creator-derived videos, transcripts, review candidates and annotations.
- Authorization screenshots or private messages.
- API keys, SSH aliases, host addresses and credentials.
- Intermediate model-training artifacts.

## Runtime dependencies

KataGo, Qwen, `llama.cpp`, ROCm and OpenCL retain their original licenses and distribution terms. Users must obtain compatible model files separately.

## Training statement

The submitted main runtime is an evidence-grounded Qwen3.6-27B agent pipeline. It does not claim that creator-derived video data was used in the public model weights. Historical small-model experiments are not the production inference path and are not included here.
