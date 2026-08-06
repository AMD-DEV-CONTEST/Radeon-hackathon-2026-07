# PrivatePlate Terminal Finalization A/B

- status: **ADOPTABLE_CANDIDATE**
- target samples: A=9, B=9

## Target E2E latency

| Metric | A model | B trusted presenter | Change B vs A |
| --- | ---: | ---: | ---: |
| p50 (ms) | 16882.65 | 4763.24 | -71.79% |
| p90 (ms) | 40133.17 | 25308.79 | -36.94% |

## Model calls

- target calls: A=34, B=21, change=-38.24%
- including setup: A=67, B=45, change=-32.84%
- prompt tokens: A=152409, B=99053, change=-35.01%
- completion tokens: A=4871, B=1802, change=-63.01%

## By-scenario target metrics

| Scenario | A p50 | B p50 | Change | A calls | B calls | Call change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| basic-planning | 38601.97ms | 19289.46ms | -50.03% | 19 | 12 | -36.84% |
| meal-completion | 11036.15ms | 1981.89ms | -82.04% | 6 | 3 | -50% |
| rag-caregiver-preview | 16882.65ms | 4763.24ms | -71.79% | 9 | 6 | -33.33% |

## Quality

- A pass/fail/errors: 7/2/0
- B pass/fail/errors: 9/0/0
- quality not lower: true
- no new errors: true

## Correction

仅修正分场景 quality 汇总；没有重新测量；原始任务和性能数据未修改。

## Conclusion

Trusted Presenter only runs after a successful terminal Domain tool. The model still selects tools, dishes, budget share and selectionReason; the presenter uses the model-submitted semantic fields and Domain-verified result.
