# YIJIAN Project Specification

## 1. Problem and users

Go review tools often show engine numbers without teaching the reason, while generic chat models can invent coordinates or confuse commentary with engine evidence. YIJIAN serves amateur players, teachers, clubs, and competition demonstrators who need an interactive explanation whose claims can be traced to the board, rules, KataGo, retrieval, or explicit human instruction.

The main workflow is: import an SGF, select a move, ask about the actual move or the AI choice, inspect the Agent plan and evidence, ask follow-up questions, and optionally save one compact lesson.

## 2. System architecture

The canonical diagram is [ARCHITECTURE.svg](ARCHITECTURE.svg).

~~~text
Browser
  -> FastAPI Agent Orchestrator
  -> bounded planner / tool whitelist
  -> goboard + KataGo + local RAG + opt-in memory
  -> immutable evidence bundle
  -> Qwen3-14B + YIJIAN LoRA v3 on W7900 / ROCm
  -> validators / deterministic fallback
  -> teaching answer and interactive board
~~~

Three trust zones are explicit:

1. **Local privacy zone:** SGFs, sessions, memory, and the browser UI.
2. **Authoritative evidence zone:** goboard legality/capture/liberty facts and KataGo analysis. The LLM cannot rewrite this layer.
3. **Radeon compute zone:** Qwen3-14B + LoRA and KataGo run on the W7900; only bounded evidence and prompts enter inference.

## 3. Agent responsibilities

The orchestrator binds the question target and accepts only the `agent-plan-v1` schema. Legal tools are limited to position inspection, move comparison, variation analysis, principle retrieval, and explicit memory operations. Coordinates and numeric board facts are forbidden in planner output.

The server executes tools, hashes the results, and creates an evidence bundle. The answer model explains that bundle; validators check JSON structure, allowed coordinates, supported numeric claims, source boundaries, and target alignment. If planning, model inference, RAG, or KataGo fails, deterministic fallback preserves the board and basic review.

## 4. Model and evidence roles

- **Qwen3-14B + YIJIAN LoRA v3:** bounded planning, concise pedagogical synthesis, and follow-up generation.
- **KataGo 1.16.5 with the registered official b40 network:** current-position best move, candidates, PVs, win rate, and score lead.
- **goboard:** legal replay, turn, captures, liberties, ko, and position hashing.
- **Local RAG:** source-labelled Go principles and terminology; never promoted to current-position engine fact.
- **Opt-in memory:** explicit, reversible lesson storage. The model has no implicit write authority.

## 5. Training data

The creator corpus contains 64 human-signed units from authorized videos, isolated by video into 48 train, 8 dev, and 8 sealed units. Cross-split checks cover video, game identity, position hash, canonical SGF identity, and eight board symmetries.

The SFT train set contains exactly 720 records: 216 planner, 288 answer, 144 follow-up, and 72 memory/privacy. It combines 48 creator train cases, 96 project-original cases, and 64 public-domain cases through deterministic projection. The 24 dev records are used for model checks. The 24 sealed records are never passed to tokenization, training, checkpoint selection, or hyperparameter decisions.

## 6. Radeon / ROCm implementation

Training uses BF16 LoRA on a Radeon PRO W7900 (gfx1100). The v3 adapter uses rank 8, alpha 16, dropout 0.10, learning rate `3e-5`, and attention projection targets. Inference uses a separate ROCm vLLM environment and the already downloaded fixed-revision Qwen3-14B base. The adapter is loaded dynamically; it is not merged into a redistributed base model.

The formal coexistence matrix uses `gpu-memory-utilization` 0.72, 0.75, and 0.78 with 30 real overlap cycles per profile. KataGo analyzes the next position while the LoRA model explains the previous evidence bundle. A profile must complete 30/30 cycles with zero OOM/restart and combined P95 at or below 12 seconds. The lowest passing memory fraction is preferred.

Prefix-cache and context-length measurements from a superseded adapter are not claimed for v3. A v3 rerun remains a separate optimization task and does not overwrite the verified coexistence matrix.

## 7. Validation and rollback

The release gate requires the data manifest, smoke, micro, full training, frozen adapter hash, 220 Agent cases, 24 failure/privacy cases, 40 unseen positions, a 30-question anonymous three-model human review, one sealed evaluation, the coexistence matrix, and a clean public snapshot.

The alias changes only after all gates pass. A failed adapter is quarantined. Any gate failure leaves the stable 27B service active and is reported without qualification.

<!-- pagebreak -->

## 8. Privacy, licensing, and limitations

Creator data is authorized for non-commercial research and competition demonstration, not asserted as a commercial license. Private games, raw videos, transcripts, reviewer comments, databases, sealed cases, weights, and adapters are excluded from the public repository. Public-domain quotations are short and registry-bound; project explanations remain project-original.

YIJIAN does not replace a professional teacher, and a 128-visit KataGo result is not proof. The evidence boundary is visible. Small-board teaching positions may differ from full-board play and are labelled.

## 9. Current completion state

Smoke, micro, and the exact 2-epoch full training passed, and YIJIAN LoRA v3 is frozen with immutable hashes. The formal runtime suite passed 220/220 Agent cases and 24/24 failure/privacy cases. The unseen suite passed its ≥95% gate at 39/40 evidence-faithful structured outputs, with zero severe contradictions and zero fabricated sources. All three W7900 coexistence profiles completed 30/30 cycles without OOM; the selected 0.72 profile achieved a 10.3355-second combined P95 while retaining the most KataGo headroom.

The anonymous human review is complete. The stable 27B scored 4.6133, the base 14B scored 2.8500, and YIJIAN LoRA scored 2.5400, with five severe contradictions assigned to the LoRA. Because the candidate failed every blind-release gate, the sealed test remains unopened with access count zero and the competition alias remains on the stable 27B service. The English competition presentation is included; the owner is recording the demonstration today and will add its English-subtitled link before the deadline.
