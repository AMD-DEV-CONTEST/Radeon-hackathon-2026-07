# Synthetic Supplier Matrix Rules

These rules apply only to the PolicySeal competition supplier-comparison fixture.

<!-- evidence-id: EV-XLSX-001 -->
## Internal procurement view

The internal procurement lead may use supplier offers, internal cost, scores, and decision notes
for a procurement decision. Contact data is limited to names and work email, and bank accounts are
excluded because payment execution is not the stated purpose.

<!-- evidence-id: EV-XLSX-002 -->
## External financial audit view

The annual financial auditor receives supplier identity and amounts necessary to substantiate the
audit. Contacts and scores are removed, account numbers show only the last four digits, and
internal comments are reduced to Approved, Pending, or Rejected.

<!-- evidence-id: EV-XLSX-003 -->
## Bidder feedback view

Bidder A receives general feedback, its own offer, and only its own generalized shortlist status.
Contacts, payment data, internal cost, and internal comments are excluded.

<!-- evidence-id: EV-XLSX-004 -->
## Supplier ownership filtering

Supplier-owned rows carry a controlled owner identifier. In bidder feedback, rows owned by a
different supplier are treated as competitor information and filtered with their prices and
scores.
