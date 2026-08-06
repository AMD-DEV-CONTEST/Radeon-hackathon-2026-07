#[derive(Clone)]
pub struct MoveOrderExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::MoveOrder>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> MoveOrderExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::MoveOrder>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::MoveOrder> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::MoveOrder> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::MoveOrder {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_move_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("move_date", |entity| entity.eval_move_date());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_estimated_weight(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("estimated_weight", |entity| entity.eval_estimated_weight());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, teaql_core::time::Timestamp> {
        let next = self.result.and_then("create_time", |entity| entity.eval_create_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_update_time(self) -> crate::ValueExpression<'a, teaql_core::time::Timestamp> {
        let next = self.result.and_then("update_time", |entity| entity.eval_update_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_version(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("version", |entity| entity.eval_version());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_customer_profile_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("customer_profile_id", |entity| entity.eval_customer_profile_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_origin_address_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("origin_address_id", |entity| entity.eval_origin_address_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_destination_address_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("destination_address_id", |entity| entity.eval_destination_address_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_move_status_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("move_status_id", |entity| entity.eval_move_status_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_customer_profile(self) -> crate::CustomerProfileExpression<'a> {
        let next = self.result.and_then("customer_profile", |entity| entity.eval_customer_profile());
        crate::CustomerProfileExpression::new(next, self.root_desc.clone())
    }

    pub fn get_origin_address(self) -> crate::LocationAddressExpression<'a> {
        let next = self.result.and_then("origin_address", |entity| entity.eval_origin_address());
        crate::LocationAddressExpression::new(next, self.root_desc.clone())
    }

    pub fn get_destination_address(self) -> crate::LocationAddressExpression<'a> {
        let next = self.result.and_then("destination_address", |entity| entity.eval_destination_address());
        crate::LocationAddressExpression::new(next, self.root_desc.clone())
    }

    pub fn get_move_status(self) -> crate::MoveStatusExpression<'a> {
        let next = self.result.and_then("move_status", |entity| entity.eval_move_status());
        crate::MoveStatusExpression::new(next, self.root_desc.clone())
    }
    pub fn move_status_is_scheduled(self) -> crate::ValueExpression<'a, bool> {
        let next = self.result.and_then("move_status_id", |entity| {
            if !entity.is_loaded("move_status_id") {
                teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_status_id".to_string(), attempted_path: "move_status_id".to_string() }
            } else {
                teaql_core::eval::EvalResult::Value(entity.move_status_is_scheduled())
            }
        });
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn move_status_is_in_transit(self) -> crate::ValueExpression<'a, bool> {
        let next = self.result.and_then("move_status_id", |entity| {
            if !entity.is_loaded("move_status_id") {
                teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_status_id".to_string(), attempted_path: "move_status_id".to_string() }
            } else {
                teaql_core::eval::EvalResult::Value(entity.move_status_is_in_transit())
            }
        });
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn move_status_is_delivered(self) -> crate::ValueExpression<'a, bool> {
        let next = self.result.and_then("move_status_id", |entity| {
            if !entity.is_loaded("move_status_id") {
                teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_status_id".to_string(), attempted_path: "move_status_id".to_string() }
            } else {
                teaql_core::eval::EvalResult::Value(entity.move_status_is_delivered())
            }
        });
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn move_status_is_cancelled(self) -> crate::ValueExpression<'a, bool> {
        let next = self.result.and_then("move_status_id", |entity| {
            if !entity.is_loaded("move_status_id") {
                teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_status_id".to_string(), attempted_path: "move_status_id".to_string() }
            } else {
                teaql_core::eval::EvalResult::Value(entity.move_status_is_cancelled())
            }
        });
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_route_plan_list(self) -> crate::RoutePlanListExpression<'a> {
        let next = self.result.and_then("route_plan_list", |entity| entity.eval_route_plan_list());
        crate::RoutePlanListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_fulfillment_event_list(self) -> crate::FulfillmentEventListExpression<'a> {
        let next = self.result.and_then("fulfillment_event_list", |entity| entity.eval_fulfillment_event_list());
        crate::FulfillmentEventListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_job_assignment_list(self) -> crate::JobAssignmentListExpression<'a> {
        let next = self.result.and_then("job_assignment_list", |entity| entity.eval_job_assignment_list());
        crate::JobAssignmentListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_customer_feedback_list(self) -> crate::CustomerFeedbackListExpression<'a> {
        let next = self.result.and_then("customer_feedback_list", |entity| entity.eval_customer_feedback_list());
        crate::CustomerFeedbackListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_box_rental_list(self) -> crate::BoxRentalListExpression<'a> {
        let next = self.result.and_then("box_rental_list", |entity| entity.eval_box_rental_list());
        crate::BoxRentalListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_invoice_document_list(self) -> crate::InvoiceDocumentListExpression<'a> {
        let next = self.result.and_then("invoice_document_list", |entity| entity.eval_invoice_document_list());
        crate::InvoiceDocumentListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_payment_record_list(self) -> crate::PaymentRecordListExpression<'a> {
        let next = self.result.and_then("payment_record_list", |entity| entity.eval_payment_record_list());
        crate::PaymentRecordListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_expense_record_list(self) -> crate::ExpenseRecordListExpression<'a> {
        let next = self.result.and_then("expense_record_list", |entity| entity.eval_expense_record_list());
        crate::ExpenseRecordListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_audit_log_list(self) -> crate::AuditLogListExpression<'a> {
        let next = self.result.and_then("audit_log_list", |entity| entity.eval_audit_log_list());
        crate::AuditLogListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct MoveOrderListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::MoveOrder>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> MoveOrderListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::MoveOrder>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::MoveOrder>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::MoveOrder>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::MoveOrder> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::MoveOrderExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::MoveOrderExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::MoveOrderExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::MoveOrderExpression::new(next, self.root_desc.clone())
    }
}