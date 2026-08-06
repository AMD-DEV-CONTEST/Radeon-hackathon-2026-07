# Supply Chain V3

Supply Chain V3 is the fail-closed admission layer for TODO 0401–0450. It does
not decide law and it never treats public availability as permission. It
extracts explicit metadata, binds each source to a revision and SHA-256, emits
risk signals, records lifecycle events, and blocks training unless the selected
use profile is mechanically satisfied.

## Frozen contract

Every `LicensedSource` carries a typed source kind, raw URI, commit, revision,
content SHA-256, author attribution, content-addressed license evidence,
training and distribution permissions, commercial and geographic restrictions,
termination terms, and media type. The policy sets are deliberately disjoint:
`allow`, `research_isolation`, `deny`, and the implicit `review` state for
everything unknown. These are ProofLaunch admission rules, not universal legal
conclusions.

Seven parsers cover GitHub SPDX, model cards, dataset cards, fonts, music,
images, and video. A parser accepts only an explicit license identifier plus a
rights locator. GitHub `NOASSERTION`/`OTHER`, a missing custom-license link, or
an unknown identifier cannot be promoted automatically. GitHub itself notes
that its license endpoint identifies the repository license file and does not
cover dependency licenses or other documentation; this is why a repository
badge cannot satisfy the full gate.

The scanner emits redacted, digest-only signals for README prompt injection,
secrets, PII, likeness/digital replicas, trademarks, sensitive industries, and
long text without explicit rights. A finding is not a legal determination. A
high-risk finding moves the source to quarantine until a named human records an
approval or rejection.

## Profiles and lifecycle

- `research` may admit an explicitly research-isolated license when all stated
  terms still permit the exact use.
- `commercial` and `competition` require training and redistribution permission
  and reject noncommercial or unresolved geographic restrictions.
- Unknown termination terms, a denied/review license, revision drift, hash
  drift, opt-out, deletion, unresolved risk, or missing observation blocks the
  run.

Registration, quarantine, approval, rejection, opt-out, and deletion are an
append-only SHA-256 event chain. Offline fallback is valid only for the exact
revision and hash, only while deletion has not been recorded, and may embed
bytes only when redistribution is permitted.

## Reproducible evidence

```bash
PYTHONPATH=src python scripts/build_v10_supply_chain.py
PYTHONPATH=src python -m unittest -v tests.test_v10_supply_chain
```

The builder uses seven small ProofLaunch-owned metadata fixtures and no
third-party expressive assets. It produces five BOMs, seven parser receipts,
offline-snapshot checks, a Dataset Card, a full per-source license gate, and a
frozen Supply Chain Report. Negative controls prove that drift, unresolved
high-risk content, and opt-out are rejected. Passing these mechanics does not
grant rights to any future source.

Key outputs:

- `data/v10_supply_chain/sources.jsonl`
- `data/v10_supply_chain/license-parser-receipts.json`
- `data/v10_supply_chain/boms.json`
- `data/v10_supply_chain/offline-snapshots.json`
- `evidence/v10/supply-chain-full-license-gate.json`
- `evidence/v10/supply-chain-dataset-card.json`
- `evidence/v10/supply-chain-v3-report.json`
- `evidence/v10/supply-chain-v3-audit.json`

## Authoritative design references

- [SPDX license expressions](https://spdx.github.io/spdx-spec/v3.0.1/annexes/spdx-license-expressions/)
- [GitHub license API](https://docs.github.com/en/rest/licenses/licenses)
- [Hugging Face model cards](https://huggingface.co/docs/hub/model-cards)
- [Hugging Face dataset cards](https://huggingface.co/docs/hub/datasets-cards)
- [SIL Open Font License 1.1](https://openfontlicense.org/open-font-license-official-text/)
- [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/)

Creative Commons explicitly warns that privacy, publicity, moral, and trademark
rights may remain outside the copyright license. Those rights therefore remain
separate risk gates here.
