# Eager vs Targeted compile closed-loop paired A/B

| Fruit | Eager success | Targeted compile success | Success match | Exact steps | Eager steady ms | Targeted compile steady ms | Speedup |
|---|---:|---:|---:|---:|---:|---:|---:|
| banana | 99/100 | 99/100 | 98/100 | 30/100 | 8.658 | 6.313 | 1.371x |
| lemon | 95/100 | 94/100 | 99/100 | 52/100 | 8.654 | 6.397 | 1.353x |
| plum | 24/100 | 29/100 | 89/100 | 77/100 | 8.373 | 6.227 | 1.345x |

- Overall success: eager 218/300, Targeted compile 222/300.
- Paired success agreement: 286/300; exact termination-step agreement: 159/300.
- Weighted steady latency: eager 8.521 ms, Targeted compile 6.295 ms, speedup 1.354x.
- Mean first-call latency per episode: eager 217.089 ms, Targeted compile 238.501 ms.
- Total rollout wall time: eager 3842.979 s, Targeted compile 3635.694 s.
