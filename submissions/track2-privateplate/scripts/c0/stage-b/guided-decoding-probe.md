# Guided / structured decoding probe (vLLM 0.25.1)

Date: 2026-08-04  
Endpoint: `http://127.0.0.1:8000` (`google/gemma-4-12B-it-qat-w4a16-ct`, `max_model_len=16384`)  
vLLM: `0.25.1` (from `/version`)

## Production failure reproduced

From diagnostic `sealed-suite-diag-16k-20260804T113546Z` / `ppb-001` FINAL_ONLY exchanges:

```text
finish_turn arguments:
{"goal": "\"compose_meal\"", "message": "..."}
```

`tool_choice: "required"` with tools `[ask_user, finish_turn]` does **not** enforce the `goal` enum. Retries repeat the same double-quoted enum. Provider then marks `control_schema_invalid` → format_retry → deterministic_fallback.

Business-tool JSON in the same turn was usually well-formed; the envelope break concentrates on control `finish_turn`.

## Mechanisms tested

Each of 3 adversarial prompts × 5 trials (unless noted). Tools used: `get_day_context` + `finish_turn` (strict JSON schemas).

| Mechanism | Result | Notes |
|-----------|--------|-------|
| `tools` + `tool_choice: "required"` | 15/15 on *weak* synthetic prompts; **fails in production FINAL_ONLY** | Built-in tool schema constraint does not stop `"\\"compose_meal\\""` |
| Named `tool_choice: finish_turn` | Same as above on weak prompts | |
| `guided_json` (+ tools) | Appears 15/15 but **ignored** | Impossible-enum `guided_json` still yields `compose_meal` |
| `guided_json` alone (no tools) | **Broken** | Free-form prose / markdown, not JSON |
| `structured_outputs: { json }` + tools | **HTTP 400** | `You can only either use constraints for structured outputs or tools, not both.` |
| `response_format: json_schema` + tools | Fails / no usable tool call | Incompatible with tools |
| `structured_outputs: { json }` **without tools** | **Works** | Impossible enum forced to `ZZZ_ONLY_ALLOWED` |
| `response_format: json_schema` without tools | **Works** | Same |
| Envelope `oneOf` `{name, arguments}` via `structured_outputs.json` | **5/5** adversarial (no double-quoted goal) | Selected approach |
| `structural_tag` | Works | Optional; envelope JSON is simpler for our provider |

### Latency sample (named finish_turn, n=3)

| Mode | latency ms | completion tokens |
|------|------------|-------------------|
| tools baseline | 1023 / 1011 / 1071 | 26 |
| tools + guided_json (ignored) | 1012 / 1013 / 1127 | 26 |

Envelope `structured_outputs` oneOf (finish vs get_day): ~1.7–2.0s TTFT+decode for short answers on this host (includes prompt); comparable order of magnitude to tool calls for short control turns.

## Conclusion

1. **vLLM 0.25.1 cannot add `guided_json` / `structured_outputs` on top of OpenAI `tools`.**
2. **Native tool calling does not reliably constrain Gemma4 tool argument enums** in our FINAL_ONLY path.
3. **Viable generation-layer fix:** drop `tools` on the wire for **FINAL_ONLY / BLOCKED**; send a **tool-envelope JSON schema** (`oneOf` per available control tool) via `structured_outputs: { json: ... }`; provider synthesizes a single tool call from `message.content`. Keep **native OpenAI tools** on ACTION_ALLOWED — full-tool oneOf envelopes can deadlock xgrammar into whitespace padding until `max_tokens` (observed in diagnostic R1: Model 3/21).
4. Keep existing schema-retry / deterministic_fallback as safety nets; also unwrap one JSON string layer on control `goal` (`"\"compose_meal\""` → `compose_meal`).
5. **No vLLM restart required** for this path (request-level `structured_outputs` already accepted by the running server). Profile notes document the client strategy; embedding `:8001` unchanged.

### Follow-up (diagnostic R1 after envelope-everywhere)

| Observation | Detail |
|-------------|--------|
| Scores | Model 3/21, Product 4/21, Safety 17/21 |
| Hang signature | `finish_reason=length`, content mostly spaces/newlines after `{"name":"get_day_context","arguments":{"goal":"inspect_context"` |
| Rate | 12/65 model HTTP calls whitespace-heavy + unparseable |
| Mitigation | Scope envelope to control modes; strip `pattern`; default string `maxLength` |

## Commands (representative)

```bash
curl -s http://127.0.0.1:8000/version
# structured_outputs works without tools:
curl -s http://127.0.0.1:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model":"google/gemma-4-12B-it-qat-w4a16-ct","temperature":0,
  "messages":[{"role":"user","content":"Return JSON"}],
  "structured_outputs":{"json":{"type":"object","properties":{"goal":{"enum":["ZZZ_ONLY_ALLOWED"]},"message":{"type":"string"}},"required":["goal","message"],"additionalProperties":false}}
}'
# tools + structured_outputs rejected:
# ... error: constraints for structured outputs or tools, not both
```

Probe scripts used during this work: `/tmp/probe-guided-decoding.mjs` and ad-hoc node one-shots in the agent session.
