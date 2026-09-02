# Northbeam Software — Support Ticket Triage Policy (v3, internal)

Northbeam sells a project-tracking SaaS to small businesses. Every
incoming ticket is assigned exactly one category and one priority.

## Categories (exactly one per ticket)

- **outage** — The Northbeam service is down, unreachable, or erroring
  for the customer's whole team. Includes login page not loading for
  everyone, API returning 5xx across the board, dashboards blank for all
  users. If only a single user is affected, it is NOT an outage.
- **account_access** — A single user cannot get into their account:
  forgotten password loops, 2FA device lost, SSO misconfigured for one
  person, locked out after failed attempts, email change requests.
- **billing** — Invoices, charges, refunds, plan upgrades/downgrades,
  payment method failures, tax documents, seat-count disputes.
- **technical_issue** — The product misbehaves for the customer but the
  service is up: broken exports, sync errors, UI bugs, slow boards,
  integrations failing (Slack, calendar), data displaying incorrectly.
- **data_request** — GDPR/CCPA-style requests: export all my data,
  delete my account and data, questions about what data is stored,
  requests for audit logs of data access.
- **feature_request** — Asking for something the product does not do:
  new integrations, new report types, dark mode, API endpoints, more
  automation rules.

Tie-breakers: if a ticket mentions several issues, pick the dominant one
(the issue the customer is asking us to act on). Security concerns and
whole-team unavailability outrank everything else in the same ticket.

## Priorities

- **P1** — Whole-team service unavailability (all `outage` tickets are
  P1) OR any suspected security incident or data breach (report of
  unauthorized access, leaked credentials, seeing another company's
  data), regardless of category.
- **P2** — A single user fully blocked from working: all
  `account_access` tickets are P2 unless they involve a suspected breach
  (then P1). A `billing` payment failure that has already suspended or
  is about to suspend the workspace is P2. A `technical_issue` is P2
  when the customer states work is blocked with no workaround (e.g.,
  "we cannot invoice clients", "boards will not load for me at all").
- **P3** — Default for `billing` (disputes, refunds, invoices, plan
  changes) and `technical_issue` (bugs with workarounds, cosmetic
  errors, slow-but-working). All `data_request` tickets are P3 (30-day
  statutory clock, not an emergency).
- **P4** — All `feature_request` tickets are P4, including ones phrased
  urgently. Wanting a feature badly does not make it a defect.

## Worked examples

- "Nobody on my team can log in, the app shows a 503" → outage / P1
- "I think someone logged into my account from another country" →
  account_access / P1 (suspected breach outranks the P2 default)
- "I'm locked out after resetting my phone, need 2FA reset" →
  account_access / P2
- "Your card charge failed and now our workspace says suspended" →
  billing / P2
- "We were double-charged for March" → billing / P3
- "CSV export has been producing empty files since yesterday, we
  can't bill clients without it" → technical_issue / P2
- "The Gantt view misaligns milestones by one day" → technical_issue / P3
- "Please delete all data associated with my account" → data_request / P3
- "You should really add a Notion integration" → feature_request / P4
