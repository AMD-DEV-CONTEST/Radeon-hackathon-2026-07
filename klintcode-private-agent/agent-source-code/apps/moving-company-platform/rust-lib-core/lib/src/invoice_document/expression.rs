#[derive(Clone)]
pub struct InvoiceDocumentExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::InvoiceDocument>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> InvoiceDocumentExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::InvoiceDocument>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::InvoiceDocument> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::InvoiceDocument> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::InvoiceDocument {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_total_due(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("total_due", |entity| entity.eval_total_due());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_issue_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("issue_date", |entity| entity.eval_issue_date());
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
    pub fn get_move_order_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("move_order_id", |entity| entity.eval_move_order_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_private_customer_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("private_customer_id", |entity| entity.eval_private_customer_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_corporate_customer_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("corporate_customer_id", |entity| entity.eval_corporate_customer_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_move_order(self) -> crate::MoveOrderExpression<'a> {
        let next = self.result.and_then("move_order", |entity| entity.eval_move_order());
        crate::MoveOrderExpression::new(next, self.root_desc.clone())
    }

    pub fn get_private_customer(self) -> crate::PrivateCustomerExpression<'a> {
        let next = self.result.and_then("private_customer", |entity| entity.eval_private_customer());
        crate::PrivateCustomerExpression::new(next, self.root_desc.clone())
    }

    pub fn get_corporate_customer(self) -> crate::CorporateCustomerExpression<'a> {
        let next = self.result.and_then("corporate_customer", |entity| entity.eval_corporate_customer());
        crate::CorporateCustomerExpression::new(next, self.root_desc.clone())
    }
    pub fn get_payment_record_list(self) -> crate::PaymentRecordListExpression<'a> {
        let next = self.result.and_then("payment_record_list", |entity| entity.eval_payment_record_list());
        crate::PaymentRecordListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_vat_record_list(self) -> crate::VatRecordListExpression<'a> {
        let next = self.result.and_then("vat_record_list", |entity| entity.eval_vat_record_list());
        crate::VatRecordListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct InvoiceDocumentListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::InvoiceDocument>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> InvoiceDocumentListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::InvoiceDocument>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::InvoiceDocument>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::InvoiceDocument>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::InvoiceDocument> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::InvoiceDocumentExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::InvoiceDocumentExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::InvoiceDocumentExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::InvoiceDocumentExpression::new(next, self.root_desc.clone())
    }
}