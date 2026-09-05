# Moving Company Service Model (20 Objects)

Generate a KSML XML model for a moving and logistics company.
You MUST generate EXACTLY 20 objects.

Design the data model by picking exactly 20 entities from the following business and platform requirements:


# Core Modules

## Business Modules

### Operations & Logistics
- Moves, Routes, Time slots, Fulfillment events, Addresses

### Employees & Payroll
- Staff registry, Job assignments, Worked hours, Payroll calculations, Bonuses, Leave tracking

### Customer Management
- Private customers, Corporate customers, Linked contacts, Billing information, Customer history

### Products & Services
- Moving services, Cleaning services, Box rentals, Additional services, Service configurations and pricing

### Marketing & Sales
- Campaign management, Discount codes, Lead tracking, Conversion metrics

### Finance & Accounting
- Payments, Invoices, Expenses, VAT management, Financial summaries

### Asset Management
- Vehicles, Equipment, Consumables, Maintenance schedules

### Administration & Compliance
- Contracts, Insurance, Document storage, Audit logs

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
- You MUST generate exactly 20 objects across your files. No more, no less.
- Each object must have proper internal_type, display_name, and _module_key.
- Include relevant properties and relationships (children/container) between the objects.
- **CRITICAL**: Do NOT put all objects in one file. You MUST use `<_include file="filename.xml" />` to split the model into logical modules (e.g., `operations.xml`, `employees.xml`, etc.) to prevent output truncation. Your main file should just be `<_include>` tags pointing to the other files you generate.

CRITICAL: NEVER use reserved keywords like 'move' or 'type' for object or field names (use 'moving_event', 'item_type', 'notification_type', etc. instead). Any secret fields like 'password_hash' or 'secret' MUST be added to the _audit_mask_fields attribute of the object for privacy compliance.
