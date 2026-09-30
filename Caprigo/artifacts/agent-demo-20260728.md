# Agent demo — RX580 Vulkan (2026-07-28)

Lived proof that the OpenAI-compatible agent endpoint answers on Polaris/Vulkan (not benches only).

- Model: `b_Radford-coder-3b-128k`
- Elapsed: 8783 ms
- Tokens: prompt=104 completion=80
- Finish: stop
- DEMO-OK marker: True

## Assistant

(1) The inference stack consists of Ollama, Vulkan, and Polaris for efficient text generation.
(2) A real footgun is setting num_gpu too low, which can waste throughput by not utilizing all available GPU resources.
(3) Measured ballpark performance for 7B Q4 model at 32k tokens per second indicates a strong baseline. DEMO-OK

## Note

Endpoint host redacted for public pack. Lab HandOff retains LAN details.
