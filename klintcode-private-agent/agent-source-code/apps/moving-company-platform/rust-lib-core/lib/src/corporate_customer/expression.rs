#[derive(Clone)]
pub struct CorporateCustomerExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::CorporateCustomer>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CorporateCustomerExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::CorporateCustomer>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::CorporateCustomer> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::CorporateCustomer> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::CorporateCustomer {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_company_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("company_name", |entity| entity.eval_company_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_tax_id(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("tax_id", |entity| entity.eval_tax_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
        let next = self.result.and_then("create_time", |entity| entity.eval_create_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_update_time(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
        let next = self.result.and_then("update_time", |entity| entity.eval_update_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_version(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("version", |entity| entity.eval_version());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("company_id", |entity| entity.eval_company_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_account_manager_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("account_manager_id", |entity| entity.eval_account_manager_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company(self) -> crate::CompanyExpression<'a> {
        let next = self.result.and_then("company", |entity| entity.eval_company());
        crate::CompanyExpression::new(next, self.root_desc.clone())
    }

    pub fn get_account_manager(self) -> crate::EmployeeRecordExpression<'a> {
        let next = self.result.and_then("account_manager", |entity| entity.eval_account_manager());
        crate::EmployeeRecordExpression::new(next, self.root_desc.clone())
    }
    pub fn get_linked_contact_list(self) -> crate::LinkedContactListExpression<'a> {
        let next = self.result.and_then("linked_contact_list", |entity| entity.eval_linked_contact_list());
        crate::LinkedContactListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_billing_info_list(self) -> crate::BillingInfoListExpression<'a> {
        let next = self.result.and_then("billing_info_list", |entity| entity.eval_billing_info_list());
        crate::BillingInfoListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_interaction_history_list(self) -> crate::InteractionHistoryListExpression<'a> {
        let next = self.result.and_then("interaction_history_list", |entity| entity.eval_interaction_history_list());
        crate::InteractionHistoryListExpression::new(next, self.root_desc.clone())
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

    pub fn get_service_contract_list(self) -> crate::ServiceContractListExpression<'a> {
        let next = self.result.and_then("service_contract_list", |entity| entity.eval_service_contract_list());
        crate::ServiceContractListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct CorporateCustomerListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::CorporateCustomer>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CorporateCustomerListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::CorporateCustomer>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::CorporateCustomer>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::CorporateCustomer>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::CorporateCustomer> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::CorporateCustomerExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CorporateCustomerExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::CorporateCustomerExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CorporateCustomerExpression::new(next, self.root_desc.clone())
    }
}