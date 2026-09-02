# Meridian Consulting — Software & Equipment Purchasing Policy (v1, internal)

Refines the software and equipment rules in the Expense Approval
Routing Policy. Routing precedence rules from that policy apply.

## Software

- ALL recurring subscriptions (monthly or annual, any amount) route to
  needs_finance, because they create ongoing spend. This includes
  renewals of subscriptions Finance already approved last cycle.
- One-time software licenses follow standard amount routing: under $75
  with receipt they are NOT auto-approvable (auto_approve is only for
  meals, travel, and office_supplies) — they route to needs_manager;
  over $500 routes to needs_finance.
- App-store purchases and cloud-service credits are software. A
  personal-account subscription (e.g., an individual music service)
  is a personal item — rejected.
- Free-trial conversions that start billing count as new subscriptions
  (needs_finance), even if the first invoice is $0.

## Equipment

- Hardware under $500 with a receipt routes to needs_manager (never
  auto_approve — equipment is not an auto-approvable category).
- Hardware at or over $500 routes to needs_finance. Bundled purchases
  (laptop + dock + monitor on one receipt) are judged by the receipt
  total, not per item.
- Accessories under $50 apiece (cables, mice, adapters) may be filed
  as office_supplies ONLY if consumable in nature; anything with a
  serial number is equipment.
- Repairs to company equipment follow the amount rules for equipment.
  Repairs to personal devices are personal items — rejected.

## Security and compliance

- Software that stores client data requires a security review before
  purchase; claims for unreviewed client-data tools route to
  needs_finance with a compliance flag, regardless of amount.
- Hardware bought secondhand from private sellers (no VAT/company
  invoice) is treated as missing-receipt (needs_manager) even with a
  payment screenshot.

## Worked examples

- "$12/month Grammarly subscription, first invoice" → software /
  needs_finance (recurring)
- "$49 one-time license for a PDF tool, receipt attached" → software /
  needs_manager (one-time license; software is never auto_approved)
- "$430 monitor, receipt attached" → equipment / needs_manager
- "$1,499 laptop + dock bundle on one receipt" → equipment /
  needs_finance (bundle total over $500)
- "$18 USB-C cable with receipt" → office_supplies / auto_approve
  (consumable accessory under $50, receipt, under $75)
- "$95 Spotify annual personal plan" → reject (personal item)
