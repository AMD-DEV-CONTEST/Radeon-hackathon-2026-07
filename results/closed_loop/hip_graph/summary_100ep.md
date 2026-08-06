# Eager vs HIP Graph closed-loop paired A/B

| Fruit | Eager success | HIP Graph success | Success match | Exact steps | Eager steady ms | HIP Graph steady ms | Speedup |
|---|---:|---:|---:|---:|---:|---:|---:|
| banana | 99/100 | 99/100 | 98/100 | 32/100 | 8.623 | 6.778 | 1.272x |
| lemon | 94/100 | 94/100 | 98/100 | 65/100 | 8.430 | 6.892 | 1.223x |
| plum | 31/100 | 34/100 | 93/100 | 81/100 | 8.546 | 6.842 | 1.249x |

- Overall success: eager 224/300, HIP Graph 227/300.
- Paired success agreement: 289/300; exact termination-step agreement: 178/300.
- Weighted steady latency: eager 8.536 ms, HIP Graph 6.838 ms, speedup 1.248x.
- Mean first-call latency per episode: eager 218.482 ms, HIP Graph 127.193 ms.
- Total rollout wall time: eager 3816.004 s, HIP Graph 3636.121 s.
