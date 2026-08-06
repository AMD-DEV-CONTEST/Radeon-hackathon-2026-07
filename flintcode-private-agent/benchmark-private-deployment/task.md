# Task: Enterprise Moving Company Platform

You are an autonomous AI architect. Your task is to design and generate a massive, enterprise-grade TeaQL KSML domain model for an **Enterprise Moving Company Platform**.

## Requirements
1. The project must be named `moving-company-platform-enterprise`.
2. Generate approximately **80 objects** in total to cover the extensive business requirements.
3. Split the objects logically across different XML files using the `<_include>` tag in `main.xml`. Do NOT write all objects into one file.
4. Output the XML files in the `models/` directory of the current project.
5. Once generation is complete, use the `cargo teaql evaluate` command to verify your models.
6. The system must cover the following modules:

**Core Modules**
- Operations & logistics: moves, routes, time slots, fulfillment events, addresses
- Employees & payroll: staff registry, job assignments, worked hours, payroll calculations, bonuses, leave tracking
- Customer management: private and corporate customers, linked contacts, billing info, customer history
- Products & services: moving, cleaning, box rentals, and additional services with configurations and pricing
- Marketing & sales: campaigns, discount codes, lead tracking, conversion metrics
- Finance & accounting: payments, invoices, expenses, VAT, financial summaries
- Asset management: vehicles, equipment, consumables, maintenance schedules
- Administration & compliance: contracts, insurance, document storage, audit logs

**Platform Modules**
- User & role management: admin, manager, employee, customer access levels
- Authentication & permissions: support for magic links, role-based access control (RBAC)
- Activity logging & audit trail: full history of changes, edits, and user actions
- Versioning & soft deletes: data recovery and edit history tracking
- Notifications & automation hooks: triggers for operational or financial updates
- API-ready architecture: structured for integration with front-end and external services

## Constraints
- If a command fails twice, stop and evaluate another approach.
- You must create the `models/` directory and place the files there.
- Use `cargo teaql --input models/ rust-lib-core --output rust-lib-core` to generate the Rust project.
- Verify the generated code using `cargo check` and `cargo test` inside the generated library directory.
- Call `finish_task` once everything compiles successfully with 0 errors.
