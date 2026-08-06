# GTM Channel Portfolio V1

Date: 2026-08-01  
Runtime artifact: `channel-portfolio.json`

## Product correction

The channel system is no longer a static list of attractive destinations. Every
prepared run now produces one content-addressed portfolio covering all 12
governed GTM routes. The same artifact is shown in the human release preview,
included in the approval digest, and sealed in the downloadable bundle.

This closes the gap between “the interface shows many channels” and “the
runtime chose only two without explaining the rest.”

## Decision algorithm

`distribution_advantage_frontier_v2` is a deterministic L2 workflow. It scores
each route from the original four factors plus the company's real distribution
advantages:

1. business-model fit — B2B or B2C;
2. lifecycle fit — pre-PMF, launch, growth or mature;
3. evidence fit — ability to carry source-bound proof;
4. budget fit — zero, small or scaled.
5. company scale and sales motion;
6. brand reach and owned-audience strength;
7. community and partner access;
8. content-production capacity;
9. authorized aggregate platform-signal fit.

The strategy compiler's primary and secondary channels receive the two focus
positions. The highest two remaining eligible routes receive bounded test
positions. Every other route is observable but unscheduled, or explicitly
excluded. Ties are resolved by stable channel ID so identical inputs are byte
reproducible. The artifact also exposes a four-channel opportunity frontier,
the second-to-third-place margin and a low/medium/high separation indicator.
That indicator is not a forecast probability.

## Hard constraints

- Zero-budget mode excludes every paid route with score zero.
- Exactly two channels can be in focus.
- At most two unscheduled channels can enter the test tier.
- All channels require human review followed by manual activation.
- Automatic publishing, spend allocation and strategy mutation remain disabled.
- A portfolio is rejected if it omits or duplicates a governed route, changes
  its digest, or escapes the approval boundary.

## What each route carries

Every entry includes:

- score and reason-code breakdown;
- activation state: `focus`, `test`, `observe` or `excluded`;
- minimum viable native asset;
- preregistered measurement metric;
- distribution mechanic;
- scheduling state and release mode;
- explicit negative evidence for automatic activation and budget allocation.

## Verification

The original scenario matrix exercises all 48 combinations of:

```text
2 business models × 4 lifecycle stages × 3 budget tiers × 2 risk tiers
```

It verifies complete channel coverage, two focus positions, no more than two
test positions, zero paid leakage in zero-budget mode, and zero automatic
activation. Runtime and HTTP tests verify that the exact portfolio reaches the
approval preview and the final evidence bundle.

The V2 distribution matrix extends this to 1,920 deterministic decisions:

```text
48 core contracts × 8 distribution profiles × 5 authorized signal scenarios
```

See `docs/product/GTM_DISTRIBUTION_ADVANTAGE_V2.md` for the current operating
contract and evidence boundaries.

## Truth boundary

This algorithm makes prioritization inspectable and budget-safe. It does not
prove channel access, publication, reach, creative preference, lift, virality
or revenue. Those require a real activated experiment and source-bound outcome
evidence.
