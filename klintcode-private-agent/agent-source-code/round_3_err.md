model input: runs/run-20260801-064548/attempt-11/model/main.xml
using https://api.teaql.io/latest/generate
<!-- ephemeral -->
# KSML Evaluation Report
## 📊 Summary
- **Errors**: 1
- **Warnings**: 1
- **Suggestions**: 1
- **Solids**: 80

## Error Pattern Summary

1 errors total. Fix the largest repeated pattern first, then rerun evaluation.

| Count | Pattern | Explanation | Action |
|-------|---------|-------------|--------|
| 1 | `Missing user field` (`KSML-LOG-004`) | Logging object 'audit_log' has no recognizable user field. A logging object must include a user/operator field (e.g. user, operator, created_by, actor). | Check agents/ERROR-FIX.md, apply the smallest fix, then rerun evaluation. |


## ❌ Errors (Must Fix)

| Rule ID | Target | Error Message | Action |
|---------|--------|---------------|--------|
| `KSML-LOG-004` | `audit_log` | Logging object 'audit_log' has no recognizable user field. A logging object must include a user/operator field (e.g. user, operator, created_by, actor). | Check `agents/ERROR-FIX.md` |


## ⚠️ Warnings

| Rule ID | Target | Warning Message |
|---------|--------|-----------------|
| `KSML-DOMAIN-ROOT-002` | `` | Multiple independent business objects found: employee, customer, service_catalog, campaign, vehicle, equipment_item, role_definition, notification_rule. The model may have disconnected graphs. |


## 💡 Suggestions

| Rule ID | Target | Suggestion |
|---------|--------|------------|
| `KSML-LOG-006` | `audit_log` | Logging object 'audit_log' has no recognizable purpose field. Adding a field like purpose, reason, or event_type helps explain why the log entry exists. |


## ✅ Solids

| Rule ID | Target | Message |
|---------|--------|---------|
| `KSML-UPLOAD-001` | `` | The upload contains 1 files. |
| `KSML-UPLOAD-005` | `` | Resolved entrypoint: main.xml |
| `KSML-XML-002` | `` | The XML document main.xml was parsed successfully. |
| `KSML-ROOT-003` | `` | Root name 'moving-company-service' is well-formed. |
| `KSML-OBJECT-001` | `move_order` | Object 'move_order' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `route_plan` | Object 'route_plan' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `time_slot` | Object 'time_slot' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `fulfillment_event` | Object 'fulfillment_event' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `address_record` | Object 'address_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `employee` | Object 'employee' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `job_assignment` | Object 'job_assignment' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `worked_hours` | Object 'worked_hours' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `payroll_calculation` | Object 'payroll_calculation' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `bonus_record` | Object 'bonus_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `leave_request` | Object 'leave_request' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `customer` | Object 'customer' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `corporate_customer` | Object 'corporate_customer' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `customer_contact` | Object 'customer_contact' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `billing_info` | Object 'billing_info' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `customer_history` | Object 'customer_history' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `service_catalog` | Object 'service_catalog' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `service_config` | Object 'service_config' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `box_rental` | Object 'box_rental' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `campaign` | Object 'campaign' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `discount_code` | Object 'discount_code' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `lead_record` | Object 'lead_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `payment_record` | Object 'payment_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `invoice_record` | Object 'invoice_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `expense_record` | Object 'expense_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `vehicle` | Object 'vehicle' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `equipment_item` | Object 'equipment_item' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `maintenance_schedule` | Object 'maintenance_schedule' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `service_contract` | Object 'service_contract' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `insurance_policy` | Object 'insurance_policy' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `document_storage` | Object 'document_storage' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `audit_log` | Object 'audit_log' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `user_account` | Object 'user_account' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `role_definition` | Object 'role_definition' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `user_role_assignment` | Object 'user_role_assignment' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `notification_rule` | Object 'notification_rule' defines display name, module, and module key metadata. |
| `KSML-REFERENCE-003` | `move_order.assigned_vehicle` | Reference 'assigned_vehicle' in 'move_order' successfully resolves to target object 'vehicle'. |
| `KSML-REFERENCE-003` | `move_order.customer` | Reference 'customer' in 'move_order' successfully resolves to target object 'customer'. |
| `KSML-REFERENCE-003` | `move_order.destination_address` | Reference 'destination_address' in 'move_order' successfully resolves to target object 'address_record'. |
| `KSML-REFERENCE-003` | `move_order.origin_address` | Reference 'origin_address' in 'move_order' successfully resolves to target object 'address_record'. |
| `KSML-REFERENCE-003` | `route_plan.move_order` | Reference 'move_order' in 'route_plan' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `time_slot.move_order` | Reference 'move_order' in 'time_slot' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `fulfillment_event.move_order` | Reference 'move_order' in 'fulfillment_event' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `fulfillment_event.performed_by` | Reference 'performed_by' in 'fulfillment_event' successfully resolves to target object 'employee'. |
| `KSML-REFERENCE-003` | `address_record.customer` | Reference 'customer' in 'address_record' successfully resolves to target object 'customer'. |
| `KSML-REFERENCE-003` | `job_assignment.employee` | Reference 'employee' in 'job_assignment' successfully resolves to target object 'employee'. |
| `KSML-REFERENCE-003` | `job_assignment.move_order` | Reference 'move_order' in 'job_assignment' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `worked_hours.employee` | Reference 'employee' in 'worked_hours' successfully resolves to target object 'employee'. |
| `KSML-REFERENCE-003` | `worked_hours.move_order` | Reference 'move_order' in 'worked_hours' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `payroll_calculation.employee` | Reference 'employee' in 'payroll_calculation' successfully resolves to target object 'employee'. |
| `KSML-REFERENCE-003` | `bonus_record.employee` | Reference 'employee' in 'bonus_record' successfully resolves to target object 'employee'. |
| `KSML-REFERENCE-003` | `leave_request.employee` | Reference 'employee' in 'leave_request' successfully resolves to target object 'employee'. |
| `KSML-REFERENCE-003` | `corporate_customer.account_manager` | Reference 'account_manager' in 'corporate_customer' successfully resolves to target object 'employee'. |
| `KSML-REFERENCE-003` | `corporate_customer.customer` | Reference 'customer' in 'corporate_customer' successfully resolves to target object 'customer'. |
| `KSML-REFERENCE-003` | `customer_contact.customer` | Reference 'customer' in 'customer_contact' successfully resolves to target object 'customer'. |
| `KSML-REFERENCE-003` | `billing_info.billing_address` | Reference 'billing_address' in 'billing_info' successfully resolves to target object 'address_record'. |
| `KSML-REFERENCE-003` | `billing_info.customer` | Reference 'customer' in 'billing_info' successfully resolves to target object 'customer'. |
| `KSML-REFERENCE-003` | `customer_history.customer` | Reference 'customer' in 'customer_history' successfully resolves to target object 'customer'. |
| `KSML-REFERENCE-003` | `customer_history.performed_by` | Reference 'performed_by' in 'customer_history' successfully resolves to target object 'employee'. |
| `KSML-REFERENCE-003` | `service_config.service_catalog` | Reference 'service_catalog' in 'service_config' successfully resolves to target object 'service_catalog'. |
| `KSML-REFERENCE-003` | `box_rental.move_order` | Reference 'move_order' in 'box_rental' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `discount_code.campaign` | Reference 'campaign' in 'discount_code' successfully resolves to target object 'campaign'. |
| `KSML-REFERENCE-003` | `lead_record.campaign` | Reference 'campaign' in 'lead_record' successfully resolves to target object 'campaign'. |
| `KSML-REFERENCE-003` | `payment_record.customer` | Reference 'customer' in 'payment_record' successfully resolves to target object 'customer'. |
| `KSML-REFERENCE-003` | `payment_record.move_order` | Reference 'move_order' in 'payment_record' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `invoice_record.customer` | Reference 'customer' in 'invoice_record' successfully resolves to target object 'customer'. |
| `KSML-REFERENCE-003` | `invoice_record.move_order` | Reference 'move_order' in 'invoice_record' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `expense_record.move_order` | Reference 'move_order' in 'expense_record' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `maintenance_schedule.vehicle` | Reference 'vehicle' in 'maintenance_schedule' successfully resolves to target object 'vehicle'. |
| `KSML-REFERENCE-003` | `service_contract.customer` | Reference 'customer' in 'service_contract' successfully resolves to target object 'customer'. |
| `KSML-REFERENCE-003` | `insurance_policy.vehicle` | Reference 'vehicle' in 'insurance_policy' successfully resolves to target object 'vehicle'. |
| `KSML-REFERENCE-003` | `document_storage.related_entity` | Reference 'related_entity' in 'document_storage' successfully resolves to target object 'service_contract'. |
| `KSML-REFERENCE-003` | `audit_log.action_operator` | Reference 'action_operator' in 'audit_log' successfully resolves to target object 'user_account'. |
| `KSML-REFERENCE-003` | `user_account.employee` | Reference 'employee' in 'user_account' successfully resolves to target object 'employee'. |
| `KSML-REFERENCE-003` | `user_role_assignment.role_definition` | Reference 'role_definition' in 'user_role_assignment' successfully resolves to target object 'role_definition'. |
| `KSML-REFERENCE-003` | `user_role_assignment.user_account` | Reference 'user_account' in 'user_role_assignment' successfully resolves to target object 'user_account'. |
