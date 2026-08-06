#[derive(Clone)]
pub struct ExpenseRecordExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::ExpenseRecord>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> ExpenseRecordExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::ExpenseRecord>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::ExpenseRecord> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::ExpenseRecord> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::ExpenseRecord {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_expense_description(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("expense_description", |entity| entity.eval_expense_description());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_expense_amount(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("expense_amount", |entity| entity.eval_expense_amount());
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
    pub fn get_employee_record_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("employee_record_id", |entity| entity.eval_employee_record_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_employee_record(self) -> crate::EmployeeRecordExpression<'a> {
        let next = self.result.and_then("employee_record", |entity| entity.eval_employee_record());
        crate::EmployeeRecordExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct ExpenseRecordListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::ExpenseRecord>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> ExpenseRecordListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::ExpenseRecord>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::ExpenseRecord>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::ExpenseRecord>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::ExpenseRecord> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::ExpenseRecordExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::ExpenseRecordExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::ExpenseRecordExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::ExpenseRecordExpression::new(next, self.root_desc.clone())
    }
}