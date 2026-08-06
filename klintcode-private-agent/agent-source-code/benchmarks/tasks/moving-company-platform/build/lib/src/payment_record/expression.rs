#[derive(Clone)]
pub struct PaymentRecordExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::PaymentRecord>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> PaymentRecordExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::PaymentRecord>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::PaymentRecord> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::PaymentRecord> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::PaymentRecord {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_payment_amount(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("payment_amount", |entity| entity.eval_payment_amount());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_payment_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("payment_date", |entity| entity.eval_payment_date());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, teaql_core::time::Timestamp> {
        let next = self.result.and_then("create_time", |entity| entity.eval_create_time());
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

    pub fn get_move_order_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("move_order_id", |entity| entity.eval_move_order_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_customer_profile(self) -> crate::CustomerProfileExpression<'a> {
        let next = self.result.and_then("customer_profile", |entity| entity.eval_customer_profile());
        crate::CustomerProfileExpression::new(next, self.root_desc.clone())
    }

    pub fn get_move_order(self) -> crate::MoveOrderExpression<'a> {
        let next = self.result.and_then("move_order", |entity| entity.eval_move_order());
        crate::MoveOrderExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct PaymentRecordListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::PaymentRecord>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> PaymentRecordListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::PaymentRecord>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::PaymentRecord>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::PaymentRecord>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::PaymentRecord> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::PaymentRecordExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::PaymentRecordExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::PaymentRecordExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::PaymentRecordExpression::new(next, self.root_desc.clone())
    }
}