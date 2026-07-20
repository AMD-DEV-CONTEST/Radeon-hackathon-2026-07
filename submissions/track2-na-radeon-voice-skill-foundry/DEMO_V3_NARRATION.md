# Demo V3 Narration

Target: final public continuous product demo after freeze.

Voice: male.

Captions: burned in, plus embedded English subtitle track.

## 00:00-00:22 - Product

Radeon Voice Skill Foundry turns a private spoken operating procedure and a
real action demonstration into a reusable, governed Agent Skill. The public
interface runs on Cloudflare, while speech recognition and skill compilation
run locally on an AMD Radeon Pro W7900 with ROCm 7.2.1.

## 00:22-01:08 - Voice and Demonstration

I provide the SOP, then perform the six required actions. Each action is
accepted and stored by the server before the interface advances: open the
review, filter critical findings, confirm the responsible commitment, prepare
drafts, create tentative holds, and export the redacted report. No irreversible
mail or calendar action is executed.

## 01:08-01:42 - Radeon Compilation

The server sends the original evidence to Qwen3-ASR and Qwen3 on the W7900.
The compiler converts intent and action trace into typed constraints, allowed
capabilities, denied capabilities, tests, policy, and a GAIA-compatible
`SKILL.md`. The original transcript hash remains bound to the result.

## 01:42-02:18 - Policy and Sandbox Replay

Sandbox Replay v1 now exercises the generated contract. Positive fixtures must
complete the workflow, while adversarial fixtures attempt unsafe behavior.
`mail.send` stays denied, sensitive values remain redacted, and the report uses
approved aliases. The verifier packages receipts and artifact hashes into a
reproducible proof bundle.

## 02:18-02:52 - Promotion Impact Review

Before promotion, the product compares this candidate with the currently
promoted skill. It surfaces permission changes, runtime compatibility, proof
status, and workflow impact. Promotion is an explicit proof-bound governance
decision, not an automatic side effect of generation.

## 02:52-03:28 - Governance Audit Ledger

The promoted decision appears in the Governance Audit Ledger. Every event has a
monotonic sequence, previous hash, payload hash, and entry hash. The ledger
reconciles its events with the receipts embedded in procedural memory. Mutation
or deletion makes the ledger invalid and blocks further governance actions.
The complete chain is exportable as JSONL.

## 03:28-03:55 - Exact Reuse

When the same intent returns, the foundry resolves the identical promoted
skill, preserves its action contract, and records exact reuse evidence instead
of replanning from scratch. Changed intent does not take this shortcut; it must
compile and verify again.

## 03:55-04:10 - Close

The final path is voice, server-authoritative demonstration, Radeon inference,
least-privilege policy, adversarial proof, impact-aware promotion, tamper-evident
governance, and exact reuse, delivered through one stable public product.
