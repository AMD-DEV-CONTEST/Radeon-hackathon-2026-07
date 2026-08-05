# RadeonX Cloud development gate (2026-08-04)

Hardware: **AMD Radeon Graphics (gfx1100), 51.52 GB VRAM, RadeonX Cloud**  
Model: **Qwen3-14B BF16**, local vLLM, xgrammar J3, prefix caching enabled

This is the one allowed focused rerun after the initial gate failed. The same
five public SWE-bench Lite tasks and fixed budgets were used. The change under
test was the final product path: Aider Repo Map with one focused refresh, Edit
V2, A1, and V1R1. The recovery rerun added bounded path recovery and
occurrence-specific feedback for non-unique replacement spans, then repeated
the same 15 cells.

| Configuration | Non-empty | Replace/edit attempts | Applied | Apply rate | J3 JSON | Tests after edit |
|---|---:|---:|---:|---:|---:|---:|
| `mini-repomap-refresh` | 1/5 | n/a (J0) | n/a | n/a | n/a | 0/5 |
| `mini-edit-v2` | 2/5 | 2 | 2 | **100.0%** | 48/48 | 0/5 |
| `mini-repomap-final` | **5/5** | 5 | **5** | **100.0%** | **38/38** | 2/5 |
| New-action total | **8/10** | 7 | **7** | **100.0%** | **86/86** | 2/10 |

The final product recovery cell had zero API errors, zero patch-capture
failures, zero integrity violations, and 5/5 non-empty patches. One comparator
`mini-edit-v2` task had two transient API timeouts and is retained as an
infrastructure event rather than silently discarded. Repo Map was available
whenever extraction succeeded; unavailable extraction was recorded rather than
replaced by a file-list fallback.

## Gate decision

The final product gate is **passed**: `mini-repomap-final` achieved 5/5
non-empty patches, 5/5 applied replacements, 38/38 valid J3 actions, zero
integrity violations, and zero API/patch-capture failures. The recovery was a
single focused engineering change followed by the permitted same-15-cell
rerun. This remains a fixed-budget engineering gate, not an official
resolve-rate ranking. Seed-0 official SWE-bench scoring has since completed;
the first-ten seed-1 stability scoring remains pending.

The initial failed rerun is preserved in its original run directory for an
auditable before/after comparison.
