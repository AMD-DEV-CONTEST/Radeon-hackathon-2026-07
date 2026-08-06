#[derive(Clone)]
pub struct VatRecordExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::VatRecord>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> VatRecordExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::VatRecord>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::VatRecord> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::VatRecord> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::VatRecord {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_vat_amount(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("vat_amount", |entity| entity.eval_vat_amount());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_tax_period(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("tax_period", |entity| entity.eval_tax_period());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_filing_status(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("filing_status", |entity| entity.eval_filing_status());
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
}

#[derive(Clone)]
pub struct VatRecordListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::VatRecord>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> VatRecordListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::VatRecord>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::VatRecord>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::VatRecord>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::VatRecord> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::VatRecordExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::VatRecordExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::VatRecordExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::VatRecordExpression::new(next, self.root_desc.clone())
    }
}