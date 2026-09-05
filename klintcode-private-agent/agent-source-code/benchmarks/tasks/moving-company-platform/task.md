# Moving Company Platform

## Scenario

A full-featured SaaS platform for a mid-to-large moving company. The system
manages everything from customer quotes and move scheduling through employee
payroll, fleet maintenance, and financial reporting. The platform must handle
40+ business entities across 8 distinct modules.

## Modules

### 1. Operations & Logistics
Move orders, route planning, time-slot scheduling, fulfillment events, and
address management. A move order links a customer to origin/destination
addresses and an assigned vehicle.

### 2. Employees & Payroll
Employee registry, job assignments per move, worked-hours tracking, payroll
calculations, bonus records, and leave requests.

### 3. Customer Management
Private and corporate customers, linked contacts, billing information,
customer interaction history. Corporate customers have an account manager
(employee reference).

### 4. Products & Services
Service catalog (moving, cleaning, packing), service configurations with
pricing, and box-rental tracking per move order.

### 5. Marketing & Sales
Campaigns, discount codes (linked to campaign), lead tracking, and conversion
metrics.

### 6. Finance & Accounting
Payment records, invoices, expense records, VAT records, and financial
summaries. Payments and invoices link to both customer and move order.

### 7. Asset Management
Vehicles, equipment items, consumable items, maintenance schedules (linked to
vehicle), and inventory tracking.

### 8. Administration & Compliance
Service contracts, insurance policies (linked to vehicle), document storage,
audit logs (with operator and timestamp), user accounts, role definitions,
user-role assignments, and notification rules.

## Naming Constraints

- All entity and field names MUST be two-word compounds (e.g., `move_order`,
  `leave_request`, `action_operator`) to avoid collisions with language
  reserved keywords (`type`, `move`, `match`, `box`, etc.).
- Single-word names like `type`, `move`, `user`, `action` are **prohibited**.

## Model Structure

- Root name: `moving-company-service`
- Organization: `example`
- Output all entities in a single XML file under one `<root>` element.
- Every object must define `_name`, `_module`, and `_module_key`.
- All entities must be connected via references — no isolated/orphaned entities.

## Acceptance Criteria

1. The KSML model passes `cargo teaql --input <model> evaluation` with **zero
   errors**.
2. The model contains **at least 30 unique business objects**.
3. `cargo teaql --input <model> gen-rust-lib` succeeds and the generated
   library passes `cargo check`.
4. `cargo teaql --input <model> gen-rust-app` succeeds and the generated
   application workspace — with injected business logic — passes `cargo check`.
5. No `KSML-KEYWORD-002` (reserved keyword) violations.
6. No `KSML-DOMAIN-ROOT-002` (disconnected graph) violations.
7. All logging/audit objects include a two-word user field (e.g.,
   `action_operator`) and a timestamp field (e.g., `log_timestamp`).
