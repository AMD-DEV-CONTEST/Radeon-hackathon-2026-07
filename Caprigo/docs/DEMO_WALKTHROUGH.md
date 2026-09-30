# Caprigo AMD demo — judge walkthrough (~72s)

**Video:** https://github.com/doteyeso-ops/caprigo/blob/main/docs/demo/Caprigo_AMD_Demo.mp4  

Contest recommends 3–5 minutes; this cut is shorter but dense. Use this guide so every second maps to rubric language.

| Time (approx) | What you see | Rubric hook |
|---------------|--------------|-------------|
| 0:00–0:15 | Caprigo brand / AMD framing | Product identity (not a notebook one-off) |
| 0:15–0:35 | Overview — runtime health, tools, AMD demo agent | Functional completeness · local agent ops |
| 0:35–0:55 | Session — live agent path (RX580 host UI; hybrid reply path in VO) | Agentic tool/runtime story |
| 0:55–1:12 | Scrap→supported ask (Lemonade / ROCm / DevMaster) | Ties to **40% AMD optimization** |

## Pair with measured numbers (post-video)

Open `AMD.md`: scrap 7B ~**19** tok/s → ROCm 7B **29.21** tok/s (~**1.5×**) on contest gfx1100.

## Pair with agent proof (scrap)

`artifacts/agent-demo-20260728.md` — OpenAI-compatible agent completion on Polaris/Vulkan with DEMO-OK marker.

## Optional longer cut

If judges require wall-clock length, a 3–5 min silent screen recording of Overview→Session→Board on scrap + this VO can be spliced; core evidence is already public.
