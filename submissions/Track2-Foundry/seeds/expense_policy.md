# Meridian Consulting — Expense Approval Routing Policy (v2, internal)

Every submitted expense claim is routed to exactly one queue and tagged
with exactly one spending category.

## Categories (exactly one per claim)

- **travel** — Flights, trains, taxis/rideshare, hotels, parking,
  mileage. Includes travel booking fees.
- **meals** — Food and non-alcoholic drinks for the employee while
  working or traveling, including team lunches.
- **client_entertainment** — Meals, events, or hospitality where a
  client or prospect is present. If a client attended, it is
  client_entertainment, not meals.
- **software** — Software licenses, SaaS subscriptions, app-store
  purchases, cloud services.
- **equipment** — Hardware: laptops, monitors, peripherals, phones,
  cables, office furniture.
- **office_supplies** — Consumables: paper, pens, notebooks, printer
  ink, small desk items under $50 apiece.

Tie-breaker: categorize by what was purchased, not why. A laptop bought
for a client project is still equipment.

## Routing queues

- **auto_approve** — Claim is under $75, belongs to meals, travel, or
  office_supplies, and a receipt is attached. All three conditions
  required.
- **needs_manager** — Default queue: anything from $75 up to $500 with
  a receipt, any claim missing a receipt regardless of amount, and all
  meals claims involving 3 or more employees.
- **needs_finance** — Any claim over $500; all software claims that are
  recurring subscriptions (any amount); all client_entertainment over
  $150; any international travel; any claim submitted more than 60 days
  after the purchase date.
- **reject** — Alcohol-only purchases; traffic or parking fines; gift
  cards; personal items (clothing, groceries, personal electronics);
  duplicate submissions of an already-reimbursed expense.

Precedence when several rules match: reject beats everything;
needs_finance beats needs_manager; needs_manager beats auto_approve.
(Example: a $40 recurring software subscription with a receipt goes to
needs_finance — the subscription rule outranks the under-$75 rule.)

## Worked examples

- "$12 sandwich at the airport, receipt attached" → meals / auto_approve
- "$460 hotel night in Chicago, receipt attached" → travel / needs_manager
- "$85 team lunch for 4 engineers, receipt attached" → meals /
  needs_manager (3+ employees rule)
- "$1,200 laptop, receipt attached" → equipment / needs_finance (over $500)
- "$29/month Figma subscription" → software / needs_finance (recurring)
- "$210 dinner with the Acme client" → client_entertainment /
  needs_finance (client present, over $150)
- "$95 dinner with a client, receipt attached" → client_entertainment /
  needs_manager (client present but under $150, $75–$500 band)
- "$60 parking ticket while visiting a client" → reject (fine)
- "$45 bottle of wine for a colleague's farewell" → reject (alcohol-only)
- "Flight to the Berlin office, $780" → travel / needs_finance
  (international AND over $500)
- "$18 printer ink, no receipt" → office_supplies / needs_manager
  (missing receipt)
