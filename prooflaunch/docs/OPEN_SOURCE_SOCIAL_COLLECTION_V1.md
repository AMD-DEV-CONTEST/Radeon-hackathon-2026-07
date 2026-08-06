# Open-source social collection contract V1

## Outcome

ProofLaunch can plan bounded collection from public or account-authorized social
URLs without making the product depend on a hosted paid API. Four bounded live
paths are admitted: pinned `yt-dlp==2026.7.4`, Bluesky's credential-free public
AppView read endpoints, same-origin Mastodon public status/context endpoints,
and bounded RSS/Atom bytes parsed by pinned `feedparser==6.0.12`. Nine additional
open-source projects remain plan-only until their command, permission and output
contracts reach the same test standard.

This subsystem collects evidence for creative measurement and hypothesis
generation. It does not silently convert public content into training data and
does not publish externally.

## Pinned connector registry

| Connector | Surfaces | Main modalities | Current status |
|---|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube, Vimeo, TikTok, Facebook, X, Instagram and generic video | video, audio, text, metadata, subtitles, comments | admitted live executor |
| [gallery-dl](https://github.com/mikf/gallery-dl) | Instagram, X, Pinterest, Tumblr, Flickr, DeviantArt | image, video, text, metadata, comments | pinned, plan-only |
| [Instaloader](https://github.com/instaloader/instaloader) | Instagram | image, video, text, metadata, comments | pinned, plan-only |
| [Crawlee for Python](https://github.com/apify/crawlee-python) | public web and browser-backed surfaces | text, metadata, comments, image, video | pinned, plan-only |
| [PRAW](https://github.com/praw-dev/praw) | Reddit | text, metadata, comments and media references | pinned, plan-only |
| [atproto](https://github.com/MarshalX/atproto) | Bluesky | aggregate engagement and abstract post-format features | admitted credential-free public AppView reader |
| [Mastodon.py](https://github.com/halcy/Mastodon.py) | Mastodon | aggregate engagement and abstract status-format features | admitted same-origin public status/context reader |
| [feedparser](https://github.com/kurtmckee/feedparser) | RSS and Atom | item, timestamp and enclosure aggregates | admitted bounded-bytes parser; parser performs no network request |
| [RSSHub](https://github.com/DIYgod/RSSHub) | public feeds and thousands of community routes | text, metadata and media references | pinned, self-hosted discovery, plan-only |
| [Trafilatura](https://github.com/adbar/trafilatura) | static public web | main text, metadata, comments and image references | pinned, plan-only |
| [Scrapy](https://github.com/scrapy/scrapy) | bounded public-site crawls | structured text, metadata, comments and media references | pinned, plan-only |
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | public JS-rendered pages | clean Markdown, structured data and media references | pinned, ordinary-browser path only, plan-only |
| [Firecrawl self-hosted](https://github.com/firecrawl/firecrawl) | public page map/crawl/extract | Markdown, structured data and media references | pinned, self-hosted, plan-only |

The 13-entry registry records whether an external API key is required, whether live
execution is admitted, and any maintenance warning. `gallery-dl` is explicitly
marked for migration monitoring because its GitHub README says primary
development moved to Codeberg. A pinned GitHub commit remains for reproduction;
it is not treated as evidence of future GitHub maintenance.

## Public no-external-API-key fallback graph

Every planned source now carries an ordered, hash-bound fallback graph:

1. RSS/RSSHub discovery when the requested modality is available.
2. Trafilatura main-content extraction for ordinary public HTML.
3. Scrapy for a bounded, rate-limited public-site crawl.
4. Crawl4AI ordinary-browser rendering for public JS pages; stealth mode is
   outside the contract.
5. Self-hosted Firecrawl public-page map/crawl/extract with robots and site
   policy controls enabled.
6. Stop and request human handling when authentication, CAPTCHA, a paywall,
   explicit denial, robots policy or another access control is encountered.

The graph requires no hosted vendor API key, but “no key” is not “no rules.”
Each layer uses bounded polite backoff, never rotates identity to evade a rate
limit, and cannot promote collected raw content into training data.

Exact upstream commit hashes, licenses and execution modes are returned by
`GET /v1/social-connectors` and are frozen in
`src/prooflaunch_remix/social_collection.py`.

## Permission modes

- `owned`: media download is admitted for a source the operator owns.
- `licensed`: media download is admitted under a recorded license.
- `account_authorized`: a caller-supplied cookie file may be used with the
  admitted executor; the cookie is never returned in an API response.
- `public_measurement`: metadata-only. Media download and raw-content training
  remain disabled.

CAPTCHA, login or access-control failures produce `human_handoff_required`.
Authentication bypass, CAPTCHA bypass, paywall bypass, rate-limit evasion,
credential extraction, automatic training and automatic publishing are outside
the execution contract.

## Plan without a live crawl

```bash
curl -sS http://127.0.0.1:8080/v1/social-collection/plan \
  -H 'Content-Type: application/json' \
  --data '{
    "urls":["https://www.youtube.com/watch?v=YOUR_OWN_ASSET"],
    "modalities":["video","audio","content","metadata","comments"],
    "rights":"owned",
    "maximum_items":25,
    "maximum_bytes":100000000,
    "timeout_seconds":120,
    "retention_days":14
  }'
```

The response hashes source URLs rather than echoing them and emits a stable
`plan_sha256` for review.

## Execute the admitted slice

```bash
PYTHONPATH=src ./.venv/bin/python scripts/run_open_source_social_collection.py \
  --request /absolute/path/to/rights-reviewed-request.json \
  --output-dir /absolute/path/to/isolated-collection-output \
  --execute
```

For `account_authorized` only, add
`--cookie-file /absolute/path/to/operator-owned-cookies.txt`. The runner invokes
an argument array with `shell=False`, disables local configuration and updates,
sets item/byte/time budgets, records hashed raw receipts and writes
`collection-plan.json` plus `collection-receipt.json` into a mode-0700 output
directory. When aggregate signals are available it also writes
`creative-signal-snapshot.json` and `creative-signal-intelligence.json`.

The native public HTTP paths require credential-free HTTPS on port 443, resolve
every hostname and redirect target, reject any non-global address, limit the
response to 5 MB, allow at most three redirects and cap each timeout at 60
seconds. An authentication wall or unsupported response stops at human handoff.

## Product ingestion boundary

Raw collector output first enters isolated CAS. It must then pass rights and PII
review before derived multimodal features may become a
`ProofLaunchCreativeSignalSnapshotV1`. The launch UI accepts that safe aggregate
JSON only together with the matching `ProofLaunchOpenSourceSocialCollectionRunV2`
receipt. The server verifies the receipt self-hash, exact canonical snapshot
hash, completed connector runs, no-bypass flags, zero training admission and
zero external publication before binding both artifact SHA-256 values into the
human-approved campaign bundle. Classification is field-level: the owner product
brief remains `internal`, while the admitted signal pair is explicitly
`creative_signal_data_class=public`. This prevents public trend data from
silently downgrading the confidentiality of first-party campaign inputs.
Captions, transcripts, scripts, media URLs and user
identifiers are rejected by the signal gate. Source paths, handles, post IDs and
query strings are replaced by a host plus source hash before the signal snapshot
is created. Approved abstract hypotheses are bound into the strategy, experiment
and content-calendar documents as a pending human-review queue; they never
silently rewrite the strategy or schedule.

## Current evidence and remaining gap

- A bounded 2026-08-02 live pilot completed against public YouTube and Vimeo
  pages with `public_measurement` rights. It normalized 28 metadata signals
  (YouTube 13, Vimeo 15), produced three aggregate format hypotheses and wrote
  a self-hashed collection receipt. Raw content remained isolated; no bypass,
  training admission, strategy mutation or external publication occurred.
- The exact snapshot/receipt pair was then ingested by
  `scripts/run_public_signal_gtm_pilot.py`. The local GTM run reached
  `awaiting_human_release`, retained `data_class=internal` for the owner brief,
  bound `creative_signal_data_class=public` for the signal field and stopped
  without automatic release. The sealed receipt is
  `artifacts/public-signal-gtm-pilot-v1/pilot-receipt.json`.
- An earlier AMD YouTube/GitHub feed attempt is preserved as truthful partial
  evidence: YouTube completed with 13 signals while the GitHub feed timed out,
  so the overall run required human handoff and was not promoted.
- Unit tests cover connector selection, URL/rights/budget validation,
  metadata-only downgrade, command construction, cookie authorization,
  Bluesky/Mastodon/feed normalization, raw/source redaction, private-DNS and
  redirect SSRF rejection, response-size caps, failed-collector human handoff
  and absence of bypass flags.
- Loopback API tests cover registry visibility, plan generation and failure on
  private hosts or unsupported rights.
- These pilots prove bounded public-metadata collection and local strategy
  ingestion only. They do not prove copied-creative rights, human preference,
  publication, causal lift, revenue, 4A quality or Radeon execution. A snapshot
  without its matching collection receipt remains rejected for a public run.
- Four deterministic live paths are implemented and contract-tested without
  extending the live claim to every connector. The other nine entries are not
  represented as production-ready collectors.
