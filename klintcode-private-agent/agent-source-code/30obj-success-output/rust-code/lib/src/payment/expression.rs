#[derive(Clone)]
pub struct PaymentExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::Payment>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> PaymentExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::Payment>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::Payment> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::Payment> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::Payment {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_amount(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("amount", |entity| entity.eval_amount());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_payment_method(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("payment_method", |entity| entity.eval_payment_method());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_status(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("status", |entity| entity.eval_status());
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
    pub fn get_invoice_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("invoice_id", |entity| entity.eval_invoice_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_invoice(self) -> crate::InvoiceExpression<'a> {
        let next = self.result.and_then("invoice", |entity| entity.eval_invoice());
        crate::InvoiceExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct PaymentListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Payment>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> PaymentListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Payment>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::Payment>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::Payment>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::Payment> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::PaymentExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::PaymentExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::PaymentExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::PaymentExpression::new(next, self.root_desc.clone())
    }
}