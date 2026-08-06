# Enterprise Logistics & Moving Service Model (50 Objects)

Generate a comprehensive KSML XML model for an international enterprise moving and logistics corporation.
You MUST generate EXACTLY 50 objects.

Design the data model by picking exactly 50 entities across the following modules:

# Core Modules

## Operations & Dispatch (6 objects)
- Moving order, Dispatch plan, Transit route, Time slot, Cargo item, Pickup address

## Fleet & IoT Tracking (6 objects)
- Vehicle, Driver assignment, GPS log, Fuel log, Vehicle maintenance, Telematics device

## Warehouse & Storage (6 objects)
- Warehouse, Storage container, Container unit, Inventory check, Pallet, Storage fee

## Employees & HR (6 objects)
- Staff member, Work shift, Worked hours, Salary slip, Performance review, Safety training

## Customer & CRM (6 objects)
- Private customer, Corporate customer, Customer contact, Service quote, Feedback review, Customer loyalty

## Sales & Marketing (5 objects)
- Promotion campaign, Discount coupon, Sales lead, Sales channel, Marketing ROI

## Finance & Accounting (5 objects)
- Invoice, Payment record, Expense item, Tax record, Financial report

## Compliance & Legal (5 objects)
- Service contract, Insurance policy, Claims record, Customs declaration, Audit log

## Platform & Settings (5 objects)
- User account, User role, Access permission, System notification (use 'notification_type' instead of reserved keyword 'type'), System configuration

## Requirements
- Follow the grammar example structure exactly.
- Use only allowed value forms from the whitelist.
- You MUST generate exactly 50 objects across your files. No more, no less.
- Each object must have proper `_name`, `_module`, and `_module_key`.
- Include relevant properties and relationships (`*_type`, `*_status`, foreign keys) between the objects.
- **CRITICAL**: Do NOT put all objects in one file. You MUST use `<_include file="filename.xml" />` to split the model into 8-10 logical modules (e.g., `operations.xml`, `fleet.xml`, `warehouse.xml`, `employees.xml`, `customers.xml`, `finance.xml`, `compliance.xml`, `platform.xml`, etc.) to prevent output truncation. Each subfile MUST be wrapped in a plain `<root>...</root>` tag with `<?xml version="1.0" encoding="UTF-8"?>`.
- **CRITICAL**: Avoid circular foreign key references between pairs of objects (e.g. do NOT have `moving_order` reference `dispatch_plan="dispatch_plan()"` while `dispatch_plan` also references `moving_order="moving_order()"`). Define relationships ONLY on the child/referencing side (e.g., `dispatch_plan` points to `moving_order="moving_order()"`).
- CRITICAL: NEVER use reserved keywords like 'move', 'type', or 'library' for object or field names (use 'moving_event', 'item_type', 'notification_type', 'public_library' instead). Any secret fields like 'password_hash' MUST be added to `_audit_mask_fields`.
