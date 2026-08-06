#[derive(Clone)]
pub struct InvoiceExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::Invoice>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> InvoiceExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::Invoice>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::Invoice> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::Invoice> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::Invoice {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_invoice_number(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("invoice_number", |entity| entity.eval_invoice_number());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_total_amount(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("total_amount", |entity| entity.eval_total_amount());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_tax_amount(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("tax_amount", |entity| entity.eval_tax_amount());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_status(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("status", |entity| entity.eval_status());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_customer(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("customer", |entity| entity.eval_customer());
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
    pub fn get_payment_list(self) -> crate::PaymentListExpression<'a> {
        let next = self.result.and_then("payment_list", |entity| entity.eval_payment_list());
        crate::PaymentListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct InvoiceListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Invoice>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> InvoiceListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Invoice>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::Invoice>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::Invoice>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::Invoice> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::InvoiceExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::InvoiceExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::InvoiceExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::InvoiceExpression::new(next, self.root_desc.clone())
    }
}