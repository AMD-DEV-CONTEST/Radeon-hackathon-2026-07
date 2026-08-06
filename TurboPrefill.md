# TurboPrefill

Track: Agentic AI

## Overview

TurboPrefill is an experimental scheduling method for multi-GPU LLM inference in llama.cpp.

TurboPrefill is an alternative scheduling strategy for systems where the existing pipeline parallel implementation does not achieve efficient overlap of H2D/D2H transfers with computation.

The project focuses on reducing GPU idle time during long-context prefill by changing the scheduling of ubatches and overlapping host-device transfers with computation.

The current implementation targets CUDA and serves as a proof of concept for future ROCm adaptation.

## Repositories

Main project:
https://github.com/sergey-automation/TurboPrefill

Validation fork:
https://github.com/sergey-automation/llama.cpp/tree/b1dd9d99cf9609f90569881989e524219ac32c98

## Validation

The validation fork outputs the hash of the complete first-token logits array together with the Top-16 logits after every prefill.

Running with identical model, prompt, `-b`, and `-ub` settings using:

- `TurboPrefill=0`
- `TurboPrefill=1`

allows numerical verification that the first-token logits remain identical.

## Current status

- CUDA implementation completed.
- Validation framework completed.
- ROCm adaptation is planned.
- This submission is intended as an architectural proof of concept for AMD GPU systems.

## Scheduling concept

TurboPrefill changes only the scheduling strategy. The figure below illustrates the difference between the standard pipeline and TurboPrefill.

![](https://raw.githubusercontent.com/sergey-automation/TurboPrefill/main/stories/TurboPrefill_GoldWood.png)

## Benchmark results

### TurboPrefill Speedup over Pipeline Parallel at 16k Context Tokens

| Configuration | Model | Pipeline Parallel (tok/s) | TurboPrefill (tok/s) | Speedup |
|---------------|-------|-----------------:|---------------------:|---------:|
| **2**× RTX PRO 5000  | Llama-3-70B | 923 | 1572 | **1.7×** |
| **4**× RTX 3090 | GPT-OSS-120B | 1477 | 2758 | **1.9×** |
| **4**× RTX 3090 | Llama-3-70B  | 400 | 1208 | **3.0×** |
| **4**× RTX 5060 | Qwen2.5-VL-72B  | 303 | 604 | **1.9×** |
| **4**× RTX 5070 Ti | Llama-3-70B   | 301 | 919 | **3.0×** |
| **4**× RTX 5070 Ti | Qwen3.6-27B-MPT  | 735 | 1611 | **2.1×** |
| **5**× RTX 5060 Ti | GPT-OSS-120B | 1993 | 3886 | **1.9×** |
| **8**× RTX 5060 Ti | GPT-OSS-120B | 1963 | 4380 | **2.2×** |


### TurboPrefill Speedup over Tensor Split at 16K Context Tokens

| Configuration | Model | Tensor Split (tok/s) | TurboPrefill (tok/s) | Speedup |
|---------------|-------|-----------------:|---------------------:|---------:|
| **2**× RTX PRO 5000  | Llama-3-70B | 1287 | 1572 | **1.22×** |
| **4**× RTX 5070 Ti | Llama-3-70B   | 417  | 919 | **2.2×** |
| **4**× RTX 5070 Ti | Qwen3.6-27B-MPT  | 794| 1611 | **2.0×** |
| **4**× RTX 3090 |Llama-3-70B  | 647 | 1208 | **1.87×** |

 Detailed benchmark scripts and raw logs are available in the project repository.

## Related work

TurboPrefill also participated in OpenAI Build Week.

TurboPrefill by Trykhlieb adapted for ik_llama.cpp by Ivan Kawrakow.

https://devpost.com/software/turboprefill

 
