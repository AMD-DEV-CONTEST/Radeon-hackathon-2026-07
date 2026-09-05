#[derive(Clone)]
pub struct CustomerProfileExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::CustomerProfile>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CustomerProfileExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::CustomerProfile>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::CustomerProfile> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::CustomerProfile> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::CustomerProfile {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_profile_type(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("profile_type", |entity| entity.eval_profile_type());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_customer_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("customer_name", |entity| entity.eval_customer_name());
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
    pub fn get_account_manager_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("account_manager_id", |entity| entity.eval_account_manager_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_account_manager(self) -> crate::EmployeeRegistryExpression<'a> {
        let next = self.result.and_then("account_manager", |entity| entity.eval_account_manager());
        crate::EmployeeRegistryExpression::new(next, self.root_desc.clone())
    }
    pub fn get_service_contract_list(self) -> crate::ServiceContractListExpression<'a> {
        let next = self.result.and_then("service_contract_list", |entity| entity.eval_service_contract_list());
        crate::ServiceContractListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_document_storage_list(self) -> crate::DocumentStorageListExpression<'a> {
        let next = self.result.and_then("document_storage_list", |entity| entity.eval_document_storage_list());
        crate::DocumentStorageListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_contact_person_list(self) -> crate::ContactPersonListExpression<'a> {
        let next = self.result.and_then("contact_person_list", |entity| entity.eval_contact_person_list());
        crate::ContactPersonListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_billing_info_list(self) -> crate::BillingInfoListExpression<'a> {
        let next = self.result.and_then("billing_info_list", |entity| entity.eval_billing_info_list());
        crate::BillingInfoListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_interaction_history_list(self) -> crate::InteractionHistoryListExpression<'a> {
        let next = self.result.and_then("interaction_history_list", |entity| entity.eval_interaction_history_list());
        crate::InteractionHistoryListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_sales_lead_list(self) -> crate::SalesLeadListExpression<'a> {
        let next = self.result.and_then("sales_lead_list", |entity| entity.eval_sales_lead_list());
        crate::SalesLeadListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_move_order_list(self) -> crate::MoveOrderListExpression<'a> {
        let next = self.result.and_then("move_order_list", |entity| entity.eval_move_order_list());
        crate::MoveOrderListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_invoice_document_list(self) -> crate::InvoiceDocumentListExpression<'a> {
        let next = self.result.and_then("invoice_document_list", |entity| entity.eval_invoice_document_list());
        crate::InvoiceDocumentListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_payment_record_list(self) -> crate::PaymentRecordListExpression<'a> {
        let next = self.result.and_then("payment_record_list", |entity| entity.eval_payment_record_list());
        crate::PaymentRecordListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct CustomerProfileListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::CustomerProfile>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CustomerProfileListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::CustomerProfile>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::CustomerProfile>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::CustomerProfile>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::CustomerProfile> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::CustomerProfileExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CustomerProfileExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::CustomerProfileExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CustomerProfileExpression::new(next, self.root_desc.clone())
    }
}