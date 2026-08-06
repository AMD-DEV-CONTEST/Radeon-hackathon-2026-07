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
cargo teaql --input models/platform-modules.xml rust-assist-[action]/[entity-name]
```

> `models/platform-modules.xml` is the default model path. If the model file is located elsewhere, adjust the `--input` path to match the actual file location in this project.

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
| address | Address |
| moving_event | MovingEvent |
| route | Route |
| time_slot | TimeSlot |
| fulfillment_event | FulfillmentEvent |
| staff | Staff |
| job_assignment | JobAssignment |
| worked_hours | WorkedHours |
| payroll | Payroll |
| bonus | Bonus |
| leave_tracking | LeaveTracking |
| private_customer | PrivateCustomer |
| corporate_customer | CorporateCustomer |
| customer_contact | CustomerContact |
| moving_service | MovingService |
| cleaning_service | CleaningService |
| campaign | Campaign |
| discount_code | DiscountCode |
| lead | Lead |
| conversion_metric | ConversionMetric |
| payment | Payment |
| invoice | Invoice |
| expense | Expense |
| vat_record | VATRecord |
| financial_summary | FinancialSummary |
| vehicle | Vehicle |
| equipment | Equipment |
| consumable | Consumable |
| user | User |
| role | Role |
| permission | Permission |
| user_role | UserRole |
| role_permission | RolePermission |
| authentication_log | AuthenticationLog |
| activity_log | ActivityLog |
| notification | Notification |
| api_endpoint | ApiEndpoint |
| webhook | Webhook |


Once the command succeeds, read its output. Use the printed code as a template to write your logic.

If the command cannot be executed, stop and report the missing context. Do not invent APIs.

## Additional References

Read these only when the task requires them:

* **`RUNTIME_CUSTOM_GUIDE.md`**
  Runtime setup, framework APIs (UserContext, SmartList, WebResponse, etc.), and debugging.

* **`TOOL_API_GUIDE.md`**
  Built-in tool integrations (HTTP client, etc.).