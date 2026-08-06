# GTM public social collection V2

## Measured state

- Full sampling standard: 140 industry-market cells and 168 platform-market lanes.
- Current priority slice: 126 lanes = 9 platforms × 7 English-first markets × B2B/B2C.
- The other 42 lanes are YouTube, podcast RSS, and owned blog/newsletter.
- Homepage-bound discovery found 76 distinct candidate source slots in the 126-lane slice.
- All 76 were executed: 0 recent-qualified, 1 stale/undated, 75 human handoffs.
- A lane is not verified until it has at least 3 distinct sources and 60 public items dated within 180 days.

The production API exposes this boundary at `GET /v1/platform-market-expansion`.

## Route order by platform

| Platform | Automatic public route | Operator route | Hard fallback |
|---|---|---|---|
| LinkedIn | bounded static public metadata | official OAuth client or public-only 4CAT/Zeeschuimer export | human handoff |
| TikTok | yt-dlp / bounded public metadata | Zeeschuimer export, then 4CAT | human handoff |
| Instagram | gallery-dl; Instaloader remains shadow | Zeeschuimer export, then 4CAT | human handoff |
| Reddit | bounded public feed | PRAW/Async PRAW with operator credentials; 4CAT import | human handoff |
| X | explicit public object shadow route only | Zeeschuimer or Tweepy-authorized export | human handoff |
| Facebook | bounded public page probe | operator Facepager/4CAT export | human handoff |
| Pinterest | gallery-dl / public feed | Zeeschuimer or official-API export | human handoff |
| Bluesky | official public AppView | DID-filtered Jetstream shadow route | human handoff |
| Mastodon | same-origin public REST | Facepager export | human handoff |

Repository discovery never grants runtime admission. The digest-bound 48-project V5 registry is exposed at `GET /v1/social-oss-landscape`; 47 projects have an exact 40-character revision resolved and only 4 currently have a project-specific runtime contract.

## V5 open-source intake map

The registry separates five jobs that are often incorrectly described as one "scraper":

| Job | Primary OSS candidates | What it can prove | Admission boundary |
|---|---|---|---|
| Structured source adapter | yt-dlp, gallery-dl, ATProto, Mastodon.py, PRAW, Tweepy, Meta Business SDK, Pinterest client | Source-native IDs, timestamps, counters and public replies when exposed | Exact platform/runtime probe required; official clients need operator credentials |
| Research capture | Zeeschuimer, 4CAT, Facepager, Cornucopia, Social Feed Manager | Repeatable operator-selected collections and exports | Public-only or operator-authorized capture; imported through the bounded normalizer |
| Public-page collection runtime | Crawlee Python/JS, Scrapy, Crawl4AI, Firecrawl, Playwright, Heritrix | Retrieval and rendering of ordinary public pages | A site-specific parser and shadow comparison are required; no generic runtime is production admission |
| Evidence preservation | ArchiveBox, Browsertrix Crawler, ArchiveWeb.page, SingleFile | Rendered HTML, screenshots, WARC/WACZ and reproducible source evidence | Preserves supplied URLs; it does not discover a market or prove engagement freshness |
| Archive normalization | warcio, Minet, Arctic Shift/Pushshift tooling | Historical replay, conversion and analysis | Historical material cannot pass the 90/180-day live-signal gate by itself |

V5 access composition is explicit: 24 ordinary-public/protocol candidates, 13 credential-bound candidates, 5 operator-capture candidates, 5 archive-input candidates and 1 rejected category. These are candidate counts, not live coverage. Current candidate density is X 25, Facebook 22, Reddit 22, Instagram 21, LinkedIn 19, TikTok 18, Pinterest 18, Bluesky 15 and Mastodon 13.

## Operator-export fast path

Zeeschuimer captures only data already delivered to the operator's normal browser session and exports JSON/CSV locally. Its output, 4CAT output, Facepager output, and ordinary platform exports can enter the same public-only normalizer.

```bash
ATTESTATION='I confirm this export was captured through ordinary browsing or an authorized platform export, contains public content only, and was not obtained by bypassing authentication, CAPTCHA, paywalls, or rate limits.'

.venv/bin/python scripts/normalize_operator_social_export.py \
  --input /absolute/path/to/export.ndjson \
  --platform tiktok \
  --attestation "$ATTESTATION" \
  --output evidence/v10/operator-social-import-tiktok-v1.json
```

The normalizer:

- accepts UTF-8 JSON, NDJSON/JSONL, or CSV up to 50 MB and 10,000 rows;
- removes rows marked private, direct, followers, friends, close-friends, or only-me;
- rejects rows without a stable item identity or public HTTPS item URL;
- deduplicates identities and normalizes dates and public interaction counts;
- computes 90-day and 180-day freshness;
- stores a maximum 500-character public excerpt, hashes identities and URLs, and never stores credentials;
- fixes raw-content training admission and automatic learning-memory writes to false/zero.

## Non-negotiable boundary

No adapter may bypass authentication, CAPTCHA, paywalls, platform limits, or robots/site policy. Stealth browsers, anti-fingerprint fallbacks, internal undocumented APIs, rotating-account pools, proxy evasion, or automatic outreach are rejected. A failed public route becomes an explicit human handoff, not a retry storm or a fabricated success.
