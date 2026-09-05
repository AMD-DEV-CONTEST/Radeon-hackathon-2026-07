note: uploading models/moving-company.xml directly since no main.xml was found in directory
model input: models/
using https://api.teaql.io/latest/evaluate
<!-- ephemeral -->
# KSML Evaluation Report
## 📊 Summary
- **Errors**: 0
- **Warnings**: 4
- **Suggestions**: 5
- **Solids**: 91

## ⚠️ Warnings

| Rule ID | Target | Warning Message |
|---------|--------|-----------------|
| `KSML-ROOT-005` | `` | Please explicitly define data_service attribute on the <root> element. Candidates supported by current tech stack (java): [postgres, mysql, oracle, hana, db2, mssql, sqlserver, snowflake, mem, duck, duckdb, sqlite] |
| `KSML-DOMAIN-ROOT-002` | `` | Multiple independent business objects found: user_account, role_definition, marketing_campaign, address_record, asset_vehicle, service_catalog. The model may have disconnected graphs. |
| `KSML-PRIVACY-001-WARN` | `user_account.email_address` | Contact identifier field. Add `email_address` to `_audit_mask_fields` (e.g., `<user_account _audit_mask_fields="password_hash,email_address">`). |
| `KSML-PRIVACY-001-WARN` | `billing_info.tax_id` | Government identifier field. Add `tax_id` to `_audit_mask_fields` (e.g., `<billing_info _audit_mask_fields="tax_id">`). |


## 💡 Suggestions

| Rule ID | Target | Suggestion |
|---------|--------|------------|
| `KSML-LOG-007` | `audit_log` | Object 'audit_log' has a name ending with '_log' but is not marked as a logging object. Consider adding _log="true" if this object represents append-only log entries. |
| `KSML-PRIVACY-001-SUG` | `user_account.account_name` | Personal attribute field. Add `account_name` to `_audit_mask_fields` (e.g., `<user_account _audit_mask_fields="password_hash,account_name">`). |
| `KSML-PRIVACY-001-SUG` | `payroll_calculation.base_salary` | Financial data field. Add `base_salary` to `_audit_mask_fields` (e.g., `<payroll_calculation _audit_mask_fields="base_salary">`). |
| `KSML-PRIVACY-001-SUG` | `contact_person.phone_number` | Contact identifier field. Add `phone_number` to `_audit_mask_fields` (e.g., `<contact_person _audit_mask_fields="phone_number">`). |
| `KSML-PRIVACY-001-SUG` | `contact_person.email_address` | Contact identifier field. Add `email_address` to `_audit_mask_fields` (e.g., `<contact_person _audit_mask_fields="email_address">`). |


## Privacy Findings

| Severity | Target | Reason | Recommended Action | Regulatory Basis |
|----------|--------|--------|--------------------|------------------|
| Suggestion | `user_account.account_name` | Personal attribute field. | Add to `_audit_mask_fields="password_hash,account_name"`. | GDPR Art. 4: identifier |
| Warning | `user_account.email_address` | Contact identifier field. | Add to `_audit_mask_fields="password_hash,email_address"`. | CCPA/CPRA 1798.140: identifiers |
| Suggestion | `payroll_calculation.base_salary` | Financial data field. | Add to `_audit_mask_fields="base_salary"`. | PIPL Art. 28: financial accounts |
| Suggestion | `contact_person.phone_number` | Contact identifier field. | Add to `_audit_mask_fields="phone_number"`. | CCPA/CPRA 1798.140: identifiers |
| Suggestion | `contact_person.email_address` | Contact identifier field. | Add to `_audit_mask_fields="email_address"`. | CCPA/CPRA 1798.140: identifiers |
| Warning | `billing_info.tax_id` | Government identifier field. | Add to `_audit_mask_fields="tax_id"`. | CCPA/CPRA 1798.140: government identifiers; PIPL Art. 28: specific identity |


## ✅ Solids

| Rule ID | Target | Message |
|---------|--------|---------|
| `KSML-UPLOAD-001` | `` | The upload contains 1 files. |
| `KSML-UPLOAD-005` | `` | Resolved entrypoint: moving-company.xml |
| `KSML-XML-002` | `` | The XML document moving-company.xml was parsed successfully. |
| `KSML-ROOT-003` | `` | Root name 'moving-company-service' is well-formed. |
| `KSML-OBJECT-001` | `user_account` | Object 'user_account' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `role_definition` | Object 'role_definition' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `role_assignment` | Object 'role_assignment' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `notification_rule` | Object 'notification_rule' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `audit_log` | Object 'audit_log' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `service_contract` | Object 'service_contract' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `document_storage` | Object 'document_storage' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `insurance_policy` | Object 'insurance_policy' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `employee_record` | Object 'employee_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `leave_request` | Object 'leave_request' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `payroll_calculation` | Object 'payroll_calculation' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `bonus_record` | Object 'bonus_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `job_assignment` | Object 'job_assignment' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `worked_hours` | Object 'worked_hours' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `customer_profile` | Object 'customer_profile' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `contact_person` | Object 'contact_person' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `billing_info` | Object 'billing_info' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `interaction_history` | Object 'interaction_history' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `marketing_campaign` | Object 'marketing_campaign' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `discount_code` | Object 'discount_code' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `sales_lead` | Object 'sales_lead' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `conversion_metric` | Object 'conversion_metric' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `address_record` | Object 'address_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `move_order` | Object 'move_order' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `route_plan` | Object 'route_plan' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `time_slot` | Object 'time_slot' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `fulfillment_event` | Object 'fulfillment_event' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `asset_vehicle` | Object 'asset_vehicle' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `equipment_item` | Object 'equipment_item' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `consumable_item` | Object 'consumable_item' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `maintenance_schedule` | Object 'maintenance_schedule' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `inventory_tracking` | Object 'inventory_tracking' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `service_catalog` | Object 'service_catalog' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `service_config` | Object 'service_config' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `box_rental` | Object 'box_rental' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `invoice_document` | Object 'invoice_document' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `payment_record` | Object 'payment_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `expense_record` | Object 'expense_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `vat_record` | Object 'vat_record' defines display name, module, and module key metadata. |
| `KSML-OBJECT-001` | `financial_summary` | Object 'financial_summary' defines display name, module, and module key metadata. |
| `KSML-REFERENCE-003` | `role_assignment.role_definition` | Reference 'role_definition' in 'role_assignment' successfully resolves to target object 'role_definition'. |
| `KSML-REFERENCE-003` | `role_assignment.user_account` | Reference 'user_account' in 'role_assignment' successfully resolves to target object 'user_account'. |
| `KSML-REFERENCE-003` | `notification_rule.role_definition` | Reference 'role_definition' in 'notification_rule' successfully resolves to target object 'role_definition'. |
| `KSML-REFERENCE-003` | `audit_log.action_operator` | Reference 'action_operator' in 'audit_log' successfully resolves to target object 'user_account'. |
| `KSML-REFERENCE-003` | `audit_log.entity_reference` | Reference 'entity_reference' in 'audit_log' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `service_contract.customer_profile` | Reference 'customer_profile' in 'service_contract' successfully resolves to target object 'customer_profile'. |
| `KSML-REFERENCE-003` | `document_storage.customer_profile` | Reference 'customer_profile' in 'document_storage' successfully resolves to target object 'customer_profile'. |
| `KSML-REFERENCE-003` | `insurance_policy.asset_vehicle` | Reference 'asset_vehicle' in 'insurance_policy' successfully resolves to target object 'asset_vehicle'. |
| `KSML-REFERENCE-003` | `employee_record.user_account` | Reference 'user_account' in 'employee_record' successfully resolves to target object 'user_account'. |
| `KSML-REFERENCE-003` | `leave_request.employee_record` | Reference 'employee_record' in 'leave_request' successfully resolves to target object 'employee_record'. |
| `KSML-REFERENCE-003` | `payroll_calculation.employee_record` | Reference 'employee_record' in 'payroll_calculation' successfully resolves to target object 'employee_record'. |
| `KSML-REFERENCE-003` | `bonus_record.employee_record` | Reference 'employee_record' in 'bonus_record' successfully resolves to target object 'employee_record'. |
| `KSML-REFERENCE-003` | `bonus_record.payroll_calculation` | Reference 'payroll_calculation' in 'bonus_record' successfully resolves to target object 'payroll_calculation'. |
| `KSML-REFERENCE-003` | `job_assignment.employee_record` | Reference 'employee_record' in 'job_assignment' successfully resolves to target object 'employee_record'. |
| `KSML-REFERENCE-003` | `job_assignment.move_order` | Reference 'move_order' in 'job_assignment' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `worked_hours.employee_record` | Reference 'employee_record' in 'worked_hours' successfully resolves to target object 'employee_record'. |
| `KSML-REFERENCE-003` | `worked_hours.job_assignment` | Reference 'job_assignment' in 'worked_hours' successfully resolves to target object 'job_assignment'. |
| `KSML-REFERENCE-003` | `customer_profile.account_manager` | Reference 'account_manager' in 'customer_profile' successfully resolves to target object 'employee_record'. |
| `KSML-REFERENCE-003` | `contact_person.customer_profile` | Reference 'customer_profile' in 'contact_person' successfully resolves to target object 'customer_profile'. |
| `KSML-REFERENCE-003` | `billing_info.customer_profile` | Reference 'customer_profile' in 'billing_info' successfully resolves to target object 'customer_profile'. |
| `KSML-REFERENCE-003` | `interaction_history.customer_profile` | Reference 'customer_profile' in 'interaction_history' successfully resolves to target object 'customer_profile'. |
| `KSML-REFERENCE-003` | `interaction_history.employee_record` | Reference 'employee_record' in 'interaction_history' successfully resolves to target object 'employee_record'. |
| `KSML-REFERENCE-003` | `discount_code.marketing_campaign` | Reference 'marketing_campaign' in 'discount_code' successfully resolves to target object 'marketing_campaign'. |
| `KSML-REFERENCE-003` | `sales_lead.customer_profile` | Reference 'customer_profile' in 'sales_lead' successfully resolves to target object 'customer_profile'. |
| `KSML-REFERENCE-003` | `sales_lead.marketing_campaign` | Reference 'marketing_campaign' in 'sales_lead' successfully resolves to target object 'marketing_campaign'. |
| `KSML-REFERENCE-003` | `conversion_metric.sales_lead` | Reference 'sales_lead' in 'conversion_metric' successfully resolves to target object 'sales_lead'. |
| `KSML-REFERENCE-003` | `move_order.asset_vehicle` | Reference 'asset_vehicle' in 'move_order' successfully resolves to target object 'asset_vehicle'. |
| `KSML-REFERENCE-003` | `move_order.customer_profile` | Reference 'customer_profile' in 'move_order' successfully resolves to target object 'customer_profile'. |
| `KSML-REFERENCE-003` | `move_order.destination_address` | Reference 'destination_address' in 'move_order' successfully resolves to target object 'address_record'. |
| `KSML-REFERENCE-003` | `move_order.origin_address` | Reference 'origin_address' in 'move_order' successfully resolves to target object 'address_record'. |
| `KSML-REFERENCE-003` | `route_plan.move_order` | Reference 'move_order' in 'route_plan' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `time_slot.move_order` | Reference 'move_order' in 'time_slot' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `fulfillment_event.move_order` | Reference 'move_order' in 'fulfillment_event' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `equipment_item.asset_vehicle` | Reference 'asset_vehicle' in 'equipment_item' successfully resolves to target object 'asset_vehicle'. |
| `KSML-REFERENCE-003` | `consumable_item.asset_vehicle` | Reference 'asset_vehicle' in 'consumable_item' successfully resolves to target object 'asset_vehicle'. |
| `KSML-REFERENCE-003` | `maintenance_schedule.asset_vehicle` | Reference 'asset_vehicle' in 'maintenance_schedule' successfully resolves to target object 'asset_vehicle'. |
| `KSML-REFERENCE-003` | `inventory_tracking.equipment_item` | Reference 'equipment_item' in 'inventory_tracking' successfully resolves to target object 'equipment_item'. |
| `KSML-REFERENCE-003` | `service_config.service_catalog` | Reference 'service_catalog' in 'service_config' successfully resolves to target object 'service_catalog'. |
| `KSML-REFERENCE-003` | `box_rental.move_order` | Reference 'move_order' in 'box_rental' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `box_rental.service_catalog` | Reference 'service_catalog' in 'box_rental' successfully resolves to target object 'service_catalog'. |
| `KSML-REFERENCE-003` | `invoice_document.customer_profile` | Reference 'customer_profile' in 'invoice_document' successfully resolves to target object 'customer_profile'. |
| `KSML-REFERENCE-003` | `invoice_document.move_order` | Reference 'move_order' in 'invoice_document' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `payment_record.customer_profile` | Reference 'customer_profile' in 'payment_record' successfully resolves to target object 'customer_profile'. |
| `KSML-REFERENCE-003` | `payment_record.move_order` | Reference 'move_order' in 'payment_record' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `expense_record.move_order` | Reference 'move_order' in 'expense_record' successfully resolves to target object 'move_order'. |
| `KSML-REFERENCE-003` | `vat_record.invoice_document` | Reference 'invoice_document' in 'vat_record' successfully resolves to target object 'invoice_document'. |
| `KSML-REFERENCE-003` | `financial_summary.invoice_document` | Reference 'invoice_document' in 'financial_summary' successfully resolves to target object 'invoice_document'. |
