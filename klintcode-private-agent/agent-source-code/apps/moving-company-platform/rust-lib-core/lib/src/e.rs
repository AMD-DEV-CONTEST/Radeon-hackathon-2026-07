
// The `E` expression wrapper provides zero-cost AST traversal
// and will automatically panic if it encounters a NotLoaded error.
pub struct E;

impl E {
    pub fn company<'a>(value: &'a crate::Company) -> crate::CompanyExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("Company(id={})", value.id()));
        crate::CompanyExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn user_account<'a>(value: &'a crate::UserAccount) -> crate::UserAccountExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("UserAccount(id={})", value.id()));
        crate::UserAccountExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn role_definition<'a>(value: &'a crate::RoleDefinition) -> crate::RoleDefinitionExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("RoleDefinition(id={})", value.id()));
        crate::RoleDefinitionExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn user_role<'a>(value: &'a crate::UserRole) -> crate::UserRoleExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("UserRole(id={})", value.id()));
        crate::UserRoleExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn audit_log<'a>(value: &'a crate::AuditLog) -> crate::AuditLogExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("AuditLog(id={})", value.id()));
        crate::AuditLogExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn notification_rule<'a>(value: &'a crate::NotificationRule) -> crate::NotificationRuleExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("NotificationRule(id={})", value.id()));
        crate::NotificationRuleExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn document_storage<'a>(value: &'a crate::DocumentStorage) -> crate::DocumentStorageExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("DocumentStorage(id={})", value.id()));
        crate::DocumentStorageExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn employee_record<'a>(value: &'a crate::EmployeeRecord) -> crate::EmployeeRecordExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("EmployeeRecord(id={})", value.id()));
        crate::EmployeeRecordExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn payroll_calculation<'a>(value: &'a crate::PayrollCalculation) -> crate::PayrollCalculationExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("PayrollCalculation(id={})", value.id()));
        crate::PayrollCalculationExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn worked_hours<'a>(value: &'a crate::WorkedHours) -> crate::WorkedHoursExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("WorkedHours(id={})", value.id()));
        crate::WorkedHoursExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn bonus_record<'a>(value: &'a crate::BonusRecord) -> crate::BonusRecordExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("BonusRecord(id={})", value.id()));
        crate::BonusRecordExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn leave_request<'a>(value: &'a crate::LeaveRequest) -> crate::LeaveRequestExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("LeaveRequest(id={})", value.id()));
        crate::LeaveRequestExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn private_customer<'a>(value: &'a crate::PrivateCustomer) -> crate::PrivateCustomerExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("PrivateCustomer(id={})", value.id()));
        crate::PrivateCustomerExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn corporate_customer<'a>(value: &'a crate::CorporateCustomer) -> crate::CorporateCustomerExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("CorporateCustomer(id={})", value.id()));
        crate::CorporateCustomerExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn linked_contact<'a>(value: &'a crate::LinkedContact) -> crate::LinkedContactExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("LinkedContact(id={})", value.id()));
        crate::LinkedContactExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn billing_info<'a>(value: &'a crate::BillingInfo) -> crate::BillingInfoExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("BillingInfo(id={})", value.id()));
        crate::BillingInfoExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn interaction_history<'a>(value: &'a crate::InteractionHistory) -> crate::InteractionHistoryExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("InteractionHistory(id={})", value.id()));
        crate::InteractionHistoryExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn vehicle_asset<'a>(value: &'a crate::VehicleAsset) -> crate::VehicleAssetExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("VehicleAsset(id={})", value.id()));
        crate::VehicleAssetExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn equipment_item<'a>(value: &'a crate::EquipmentItem) -> crate::EquipmentItemExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("EquipmentItem(id={})", value.id()));
        crate::EquipmentItemExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn consumable_item<'a>(value: &'a crate::ConsumableItem) -> crate::ConsumableItemExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("ConsumableItem(id={})", value.id()));
        crate::ConsumableItemExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn maintenance_schedule<'a>(value: &'a crate::MaintenanceSchedule) -> crate::MaintenanceScheduleExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("MaintenanceSchedule(id={})", value.id()));
        crate::MaintenanceScheduleExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn inventory_tracking<'a>(value: &'a crate::InventoryTracking) -> crate::InventoryTrackingExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("InventoryTracking(id={})", value.id()));
        crate::InventoryTrackingExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn insurance_policy<'a>(value: &'a crate::InsurancePolicy) -> crate::InsurancePolicyExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("InsurancePolicy(id={})", value.id()));
        crate::InsurancePolicyExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn address_record<'a>(value: &'a crate::AddressRecord) -> crate::AddressRecordExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("AddressRecord(id={})", value.id()));
        crate::AddressRecordExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn move_order<'a>(value: &'a crate::MoveOrder) -> crate::MoveOrderExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("MoveOrder(id={})", value.id()));
        crate::MoveOrderExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn route_plan<'a>(value: &'a crate::RoutePlan) -> crate::RoutePlanExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("RoutePlan(id={})", value.id()));
        crate::RoutePlanExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn time_slot<'a>(value: &'a crate::TimeSlot) -> crate::TimeSlotExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("TimeSlot(id={})", value.id()));
        crate::TimeSlotExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn fulfillment_event<'a>(value: &'a crate::FulfillmentEvent) -> crate::FulfillmentEventExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("FulfillmentEvent(id={})", value.id()));
        crate::FulfillmentEventExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn job_assignment<'a>(value: &'a crate::JobAssignment) -> crate::JobAssignmentExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("JobAssignment(id={})", value.id()));
        crate::JobAssignmentExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn service_catalog<'a>(value: &'a crate::ServiceCatalog) -> crate::ServiceCatalogExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("ServiceCatalog(id={})", value.id()));
        crate::ServiceCatalogExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn service_config<'a>(value: &'a crate::ServiceConfig) -> crate::ServiceConfigExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("ServiceConfig(id={})", value.id()));
        crate::ServiceConfigExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn box_rental<'a>(value: &'a crate::BoxRental) -> crate::BoxRentalExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("BoxRental(id={})", value.id()));
        crate::BoxRentalExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn marketing_campaign<'a>(value: &'a crate::MarketingCampaign) -> crate::MarketingCampaignExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("MarketingCampaign(id={})", value.id()));
        crate::MarketingCampaignExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn discount_code<'a>(value: &'a crate::DiscountCode) -> crate::DiscountCodeExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("DiscountCode(id={})", value.id()));
        crate::DiscountCodeExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn lead_tracking<'a>(value: &'a crate::LeadTracking) -> crate::LeadTrackingExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("LeadTracking(id={})", value.id()));
        crate::LeadTrackingExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn conversion_metric<'a>(value: &'a crate::ConversionMetric) -> crate::ConversionMetricExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("ConversionMetric(id={})", value.id()));
        crate::ConversionMetricExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn invoice_document<'a>(value: &'a crate::InvoiceDocument) -> crate::InvoiceDocumentExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("InvoiceDocument(id={})", value.id()));
        crate::InvoiceDocumentExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn payment_record<'a>(value: &'a crate::PaymentRecord) -> crate::PaymentRecordExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("PaymentRecord(id={})", value.id()));
        crate::PaymentRecordExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn expense_record<'a>(value: &'a crate::ExpenseRecord) -> crate::ExpenseRecordExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("ExpenseRecord(id={})", value.id()));
        crate::ExpenseRecordExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn vat_record<'a>(value: &'a crate::VatRecord) -> crate::VatRecordExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("VatRecord(id={})", value.id()));
        crate::VatRecordExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn financial_summary<'a>(value: &'a crate::FinancialSummary) -> crate::FinancialSummaryExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("FinancialSummary(id={})", value.id()));
        crate::FinancialSummaryExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }

    pub fn service_contract<'a>(value: &'a crate::ServiceContract) -> crate::ServiceContractExpression<'a> {
        let root_desc = std::sync::Arc::new(format!("ServiceContract(id={})", value.id()));
        crate::ServiceContractExpression::new(teaql_core::eval::EvalResult::Value(value), root_desc)
    }
}


pub fn trigger_logic_bug_panic(root_desc: &str, failed_node: &str, attempted_path: &str) -> ! {
    let parts: Vec<&str> = attempted_path.split('.').collect();
    let break_idx = parts.iter().position(|&p| p == failed_node).unwrap_or(0);

    let mut nested_fix = String::new();
    if break_idx < parts.len() - 1 {
        nested_fix.push_str(&format!("\"select_{}(", failed_node));
        let mut close_parens = 1;
        for i in (break_idx + 1)..parts.len() {
            let sub_field = parts[i];
            let prev_field = parts[i-1];
            let is_last = i == parts.len() - 1;
            if is_last {
                nested_fix.push_str(&format!("Q::{}s().select_{}()", prev_field, sub_field));
            } else {
                nested_fix.push_str(&format!("Q::{}s().select_{}(", prev_field, sub_field));
                close_parens += 1;
            }
        }
        for _ in 0..close_parens {
            nested_fix.push(')');
        }
        nested_fix.push('"');
    } else {
        nested_fix = "null".to_string();
    }

    let suggested_fix = format!("\"select_{}()\"", failed_node);

    let access_path_json = format!("[{}]", parts.iter().map(|s| format!("\"{}\"", s)).collect::<Vec<_>>().join(", "));
    let missing_preload_json = format!("[\"{}\"]", failed_node);

    let human_nested = if nested_fix != "null" { format!(" 或完整嵌套加载 {}", nested_fix) } else { String::new() };
    let root_name = root_desc.split('(').next().unwrap_or("Unknown");

    let mut root_snake = String::new();
    for (i, c) in root_name.chars().enumerate() {
        if c.is_uppercase() {
            if i > 0 {
                root_snake.push('_');
            }
            root_snake.push(c.to_ascii_lowercase());
        } else {
            root_snake.push(c);
        }
    }
    let id_part = root_desc.split('(').nth(1).unwrap_or(")");
    let mut original_expr = format!("E::{}({}", root_snake, id_part);
    for p in &parts {
        original_expr.push_str(&format!(".get_{}()", p));
        if *p == failed_node {
            original_expr.push_str("<broken>");
        }
    }

    let human_message = format!("\"访问 {}.{} 时缺少预加载。请在查询中加入 {}{}\"", root_name, attempted_path, suggested_fix, human_nested);

    panic!("\n\n💥 [Coding Logic Bug]\n\noriginal_expr_with_broken_point: \"{}\"\nroot: {}\naccess_path: {}\nbreak_point: \"{}\"\nmissing_preload: {}\nsuggested_fix: {}\nnested_fix: {}\nseverity: \"error\"\nhuman_message: {}\n", 
        original_expr, root_desc, access_path_json, failed_node, missing_preload_json, suggested_fix, nested_fix, human_message);
}

#[derive(Clone)]
pub struct ValueExpression<'a, T> {
    result: teaql_core::eval::EvalResult<T>,
    root_desc: std::sync::Arc<String>,
    _phantom: std::marker::PhantomData<&'a ()>,
}

impl<'a, T: Clone> ValueExpression<'a, T> {
    pub fn new(result: teaql_core::eval::EvalResult<T>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc, _phantom: std::marker::PhantomData }
    }

    fn resolve(self) -> Option<T> {
        match self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(self) -> Option<T> {
        self.resolve()
    }

    pub fn unwrap(self) -> T {
        self.resolve().expect("Value was legitimately null in database!")
    }

    pub fn or_else(self, default_value: T) -> T {
        self.eval().unwrap_or(default_value)
    }

    pub fn or_else_with(self, default_fn: impl FnOnce() -> T) -> T {
        self.eval().unwrap_or_else(default_fn)
    }

    pub fn or_default(self) -> T where T: Default {
        self.eval().unwrap_or_default()
    }
}

