## Decision: Preserve the legacy crypto build and submit a separate domestic-market build
## Context: The existing pipeline and model were trained around crypto examples, while the competition submission should be suitable for a mainland-China presentation and avoid BTC-related content.
## Alternatives considered: Rewrite the existing model and Dify app in place; keep one mixed-market model; preserve the old implementation and train a separately named domestic adapter/model.
## Reasoning: Separate assets prevent regression and make the submission narrative coherent. The domestic model can encode A-share/ETF constraints without contaminating or overwriting already validated evidence.
## Trade-offs accepted: Two model variants require more storage and release documentation, and the domestic model needs its own evaluation and Dify workflow configuration.
