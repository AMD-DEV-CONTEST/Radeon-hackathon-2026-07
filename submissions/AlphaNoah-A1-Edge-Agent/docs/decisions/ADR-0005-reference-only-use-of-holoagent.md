# ADR-0005: Close HoloAgent-0 Work as Reference Only

## Status

Accepted and closed — 2026-07-23

```text
Status: Closed
Usage: Academic reference only
Source code incorporated: No
Media/assets incorporated: No
Models incorporated: No
License audit required before future integration: Yes
Current blocker: None
```

## Context

HoloAgent-0 influenced early architecture discussion, but AlphaNoah now needs to build and verify its own closed loop. No HoloAgent-0 code, model, data, figure, logo, GIF or video is present in the current implementation.

## Decision

AlphaNoah 当前仅引用 HoloAgent-0 论文作为相关工作和架构参考，不包含其源码、模型、媒体资产或衍生实现。若未来决定实际采用 HoloAgent-0 代码或资产，必须在集成前重新执行针对具体版本和具体组件的许可证审计。

Existing audit material remains historical evidence. No further investigation is performed unless one of these triggers occurs:

- code is selected for copying or modification;
- a model, container or dataset is selected;
- a figure, logo, GIF or video is selected;
- formal publication information changes;
- authors provide new license or citation instructions.

## Consequences

- HoloAgent-0 creates no current implementation blocker.
- References must say “reference/inspiration,” not “based on” or “integrated.”
- Citation does not authorize asset reuse.
