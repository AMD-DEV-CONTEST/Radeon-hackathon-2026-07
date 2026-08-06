<!-- DISCARD_BLOCK: phase_modeling -->

# TeaQL Rust Agent Instructions

> [!WARNING]
> **IGNORE GENERIC ORM EXPERIENCE**
>
> Do **not** use pre-trained habits from data-access frameworks, ORMs, or database integration libraries.
>
> Do **not** use SeaORM, Diesel, SQLx, rbatis, or similar frameworks.
>
> Do **not** write raw SQL, DAOs, Repository implementations, or custom persistence layers.
>
> Do **not** guess TeaQL method names.

## How to Write Domain Code

To get the exact API usage and query examples for the entity you are working on, execute the following command:

```bash
cargo teaql --input models/moving-company-service.xml rust-assist-[action]/[entity-name]
```

> `models/moving-company-service.xml` is the default model path. If the model file is located elsewhere, adjust the `--input` path to match the actual file location in this project.

Replace `[action]` with one of the following:

| action | when-to-use |
|--------|-------------|
| query | Read/find records from the database using Q:: |
| create | Insert a new record into the database |
| update | Modify and save an existing record |
| delete | Remove or soft-delete a record |
| expression | Safely extract nested relation values using E:: |
| list-page | Implement a paginated query returning SmartList |
| debug | View instructions for enabling SQL logging and debugging |

Replace `[entity-name]` with the exact entity-name from the table below:

| entity-name | display-name |
|-------------|--------------|
| order_status | Order Status |
| company_profile | Company Profile |
| user_account | User Account |
| role_definition | Role Definition |
| role_assignment | Role Assignment |
| notification_rule | Notification Rule |
| audit_log | Audit Log |
| service_contract | Service Contract |
| document_storage | Document Storage |
| insurance_policy | Insurance Policy |
| employee_registry | Employee Registry |
| leave_request | Leave Request |
| payroll_calculation | Payroll Calculation |
| bonus_record | Bonus Record |
| job_assignment | Job Assignment |
| worked_hours | Worked Hours |
| customer_profile | Customer Profile |
| contact_person | Contact Person |
| billing_info | Billing Info |
| interaction_history | Interaction History |
| marketing_campaign | Marketing Campaign |
| discount_code | Discount Code |
| sales_lead | Sales Lead |
| conversion_metric | Conversion Metric |
| location_address | Location Address |
| move_order | Move Order |
| route_plan | Route Plan |
| time_slot | Time Slot |
| fulfillment_event | Fulfillment Event |
| fleet_vehicle | Fleet Vehicle |
| equipment_item | Equipment Item |
| consumable_item | Consumable Item |
| maintenance_schedule | Maintenance Schedule |
| inventory_tracking | Inventory Tracking |
| service_catalog | Service Catalog |
| service_config | Service Config |
| box_rental | Box Rental |
| invoice_document | Invoice Document |
| payment_record | Payment Record |
| expense_record | Expense Record |
| vat_record | VAT Record |
| financial_summary | Financial Summary |


Once the command succeeds, read its output. Use the printed code as a template to write your logic.

If the command cannot be executed, stop and report the missing context. Do not invent APIs.

## Additional References

Read these only when the task requires them:

* **`RUNTIME_CUSTOM_GUIDE.md`**
  Runtime setup, framework APIs (UserContext, SmartList, WebResponse, etc.), and debugging.

* **`TOOL_API_GUIDE.md`**
  Built-in tool integrations (HTTP client, etc.).