# GTM distribution advantage V2

Date: 2026-08-02  
Runtime artifact: `channel-portfolio.json`

## Product decision

The channel system now chooses a defensible distribution frontier rather than
replaying a static B2B/B2C channel table. A prepared run binds its market and
campaign contract to the company's actual distribution advantages:

- company scale and sales motion;
- brand reach and owned-audience strength;
- community and partner access;
- content-production capacity;
- lifecycle, budget and industry-risk constraints;
- authorized aggregate platform-signal counts.

The same scoring surface produces the strategy focus and the complete
12-channel production portfolio. A mismatch fails verification instead of
allowing the strategy and calendar to drift apart.

## Graph, Loop and Harness

The decision is intentionally L2 automation:

1. **Graph:** typed campaign context, budget exclusion, channel frontier,
   production pack, calendar, approval preview and outcome ledger are fixed
   workflow contracts.
2. **Loop:** a model may draft, critique and repair content only inside the
   selected node and its supplied evidence envelope.
3. **Harness:** schema validation, provenance, spend and activation blocks,
   bounded retries, hashes, logging and named-human approval apply to every
   node.

No model can activate a channel, publish an asset, allocate spend or rewrite
the live strategy. Observed outcomes can propose a next-run reallocation that
requires named-human approval.

## Decision output

Every portfolio exposes:

- the complete decision context;
- whether admitted platform signals were used;
- a ranked four-channel opportunity frontier;
- two focus channels and at most two test channels;
- reason codes for every governed channel;
- the margin between the second focus and first non-focus opportunity;
- low, medium or high decision confidence;
- the manual, next-run-only reallocation policy.

Confidence is a deterministic separation indicator, not a calibrated
probability. Scores are prioritization values, not reach or revenue forecasts.

## Evaluation

The sealed matrix exercises 1,920 decisions:

```text
48 business/lifecycle/budget/risk contracts
× 8 distribution profiles
× 5 authorized signal scenarios
```

It covers every enum value for company scale, distribution strength, content
capacity and sales motion. It checks unique strategy identities, exactly two
focus channels, at most two test channels, four frontier entries, paid-channel
exclusion at zero budget, no automatic activation and no automatic
reallocation.

Evidence:

- `evidence/v10/gtm-distribution-advantage-matrix-v2.json`
- `evidence/v10/gtm-distribution-advantage-research-2026-08-02.json`

## Truth boundary

This closes a product decision and observability gap. It does not establish
platform access, publication, human creative preference, causal lift,
virality, revenue, 4A effect, universal-industry performance or Top-1 market
standing. Those remain separate live and human-evidence gates.
