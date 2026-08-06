# Space Logistics Service Model (40 Objects)

Generate a KSML XML model for an interstellar space logistics company.
You should generate approximately 40 objects.

Design the data model by picking around 40 entities from the following business and platform requirements:


# Core Modules

## Business Modules

### Operations & Logistics
- Hyperjumps, Galactic Routes, Time slots, Fulfillment events, Planetary Addresses, Sector delivery zones, Cargo loading plans

### Employees & Payroll
- Staff registry, Job assignments, Worked hours, Payroll calculations, Bonuses, Leave tracking, Skill certifications, Shift schedules

### Customer Management
- Private customers, Corporate customers, Linked contacts, Billing information, Customer history, Customer feedback, Loyalty programs

### Products & Services
- Interstellar transport services, Hull cleaning services, Cargo pod rentals, Additional services, Service configurations and pricing, Service bundles, Warranties

### Marketing & Sales
- Campaign management, Discount codes, Lead tracking, Conversion metrics, Referral programs, Partner affiliations

### Finance & Accounting
- Payments, Invoices, Expenses, VAT management, Financial summaries, Credit notes, Payment plans

### Asset Management
- Spaceships, Equipment, Antimatter Consumables, Hull maintenance schedules, Plasma fuel logs, Depreciation records

### Administration & Compliance
- Contracts, Insurance, Document storage, Audit logs, Regulatory filings, Policy documents

# Platform Modules

## System Capabilities
- User & Role Management (Admin access, Manager access, Employee access, Customer access levels)
- Authentication & Permissions (Magic link authentication, Role-Based Access Control, Permission management)
- Activity Logging & Audit Trail (Complete history of changes, Edit tracking, User activity records)
- Versioning & Data Recovery (Version history, Soft deletes, Data recovery)
- Notifications & Automation Hooks (Operational triggers, Financial update notifications, Workflow automation)
- API-Ready Architecture (Structured APIs, Front-end integration support, External service integrations)


## Requirements
- Follow the grammar example structure exactly.
- Use only allowed value forms from the whitelist.
- You should aim to generate approximately 40 objects across your files.
- Each object must have proper internal_type, display_name, and _module_key.
- Include relevant properties and relationships (children/container) between the objects.
- **CRITICAL**: Do NOT put all objects in one file. You MUST use `<_include file="filename.xml" />` to split the model into logical modules (e.g., `operations.xml`, `employees.xml`, etc.) to prevent output truncation. Your main file should just be `<_include>` tags pointing to the other files you generate.
- **CRITICAL**: Do NOT copy or manually modify `rust-lib-core` or any generated Rust code from reference projects. The `cargo teaql` compiler will automatically generate the entire new library from scratch based purely on your XML models. Focus only on generating the XML models and invoking the compiler.
- **EXECUTION PLAN**: You MUST follow these exact steps to complete the task:
  1. Immediately create `models/main.xml` with `<_include>` tags pointing to your sub-modules.
  2. Create the first domain file (e.g., `models/operations.xml`) and hand-write the XML objects from scratch based on the rules in `SKILL.md`.
  3. Continue creating the remaining domain files until approximately 40 objects are defined.
  4. Run `cargo teaql --input models/ evaluate` and fix any syntax or circular reference errors. **DO NOT attempt to manually merge XML files. The `cargo teaql` tool will automatically evaluate all `.xml` files in the directory. DO NOT use `mergemodel` or imaginary flags like `--upload`.**
  5. Run `cargo teaql --input models/ --output ../../../apps/space-logistics-platform/rust-lib-core/lib rust-lib-core` and finish the task.
  *Note: There are NO existing reference code files for this benchmark on the system. You are being evaluated purely on your ability to write the XML code completely from scratch. Do not waste time searching.*
- **CRITICAL RULE FOR TERMINAL OUTPUTS**: If you run a command and see the warning `"Tool output too large, applying head/tail truncation"`, **DO NOT rerun the exact same command.** Instead, redirect the output to a temporary file (`> /tmp/error.log`), and use `grep_search` or `view_file` to read the specific error details. Repeating the same command will trigger the loop guard and kill your process.
- **ERROR HANDLING**: If a command fails twice with the same error, **STOP**. Do not run it a third time. Use your tools to check the directory structure, read the `Cargo.toml`, or review the official `SKILL.md` documentation to find out what you are doing wrong.

CRITICAL: NEVER use reserved keywords like 'move' or 'type' for object or field names (use 'moving_event', 'item_type', 'notification_type', etc. instead). Any secret fields like 'password_hash' or 'secret' MUST be added to the _audit_mask_fields attribute of the object for privacy compliance.
