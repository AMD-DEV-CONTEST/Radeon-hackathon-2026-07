# Meridian Consulting — Travel Expense Addendum (v1, internal)

This addendum refines the travel rules in the Expense Approval Routing
Policy. Where both documents speak, the routing policy's precedence
rules win.

## Booking and class rules

- Economy class is the default for all flights under 6 hours. Premium
  economy is claimable on flights of 6 hours or longer. Business class
  requires written director approval BEFORE booking; without it, the
  claim routes to needs_finance regardless of amount.
- Hotels: the nightly cap is $260 in North America and Europe, $180
  elsewhere. A claim over the cap is not rejected — it routes to
  needs_manager with the overage noted, unless the total exceeds $500,
  which routes to needs_finance as usual.
- Rideshare and taxis follow standard routing by amount. Rental cars
  count as travel; fuel for a rental is part of the same claim.

## Mileage

- Personal-vehicle mileage is reimbursed at $0.62 per mile with an
  odometer or map screenshot as the receipt equivalent. Mileage claims
  without any distance evidence count as missing-receipt claims
  (needs_manager).
- Commuting between home and the primary office is never reimbursable —
  such claims are rejected as personal expenses.

## International travel

- ALL international travel routes to needs_finance regardless of
  amount, per the routing policy. This includes day trips across a
  border and international legs of mixed itineraries.
- Foreign-currency claims must state the original currency; the
  reimbursement uses the booking-date exchange rate. A missing currency
  statement is treated as a missing receipt (needs_manager).

## Per diems and meals while traveling

- Meals while traveling remain meals-category claims; the traveling
  context does not change the category. The 3-or-more-employees rule
  from the routing policy still applies to team meals on the road.
- Alcohol on a travel meal receipt: if the receipt is mixed
  (food + alcohol), the alcohol portion is deducted and the remainder
  is processed normally; an alcohol-only receipt is rejected per the
  routing policy.

## Worked examples

- "$240/night hotel in Denver, 2 nights, receipts attached" → travel /
  needs_manager (total $480 in the $75–$500 band; under nightly cap)
- "$310/night hotel in Zurich for one night" → travel / needs_finance
  (international)
- "148 miles driving to the client site, map screenshot attached" →
  travel / needs_manager ($91.76 at $0.62/mile, in the $75–$500 band)
- "$34 airport taxi, no receipt" → travel / needs_manager (missing
  receipt overrides the under-$75 auto_approve rule)
- "$58 dinner while at the Austin conference, receipt attached" →
  meals / auto_approve (under $75, receipt, solo)
