#[derive(Clone)]
pub struct PayrollCalculationExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::PayrollCalculation>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> PayrollCalculationExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::PayrollCalculation>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::PayrollCalculation> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::PayrollCalculation> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::PayrollCalculation {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_pay_period(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("pay_period", |entity| entity.eval_pay_period());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_base_salary(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("base_salary", |entity| entity.eval_base_salary());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
        let next = self.result.and_then("create_time", |entity| entity.eval_create_time());
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
    pub fn get_employee_record(self) -> crate::EmployeeRegistryExpression<'a> {
        let next = self.result.and_then("employee_record", |entity| entity.eval_employee_record());
        crate::EmployeeRegistryExpression::new(next, self.root_desc.clone())
    }
    pub fn get_bonus_record_list(self) -> crate::BonusRecordListExpression<'a> {
        let next = self.result.and_then("bonus_record_list", |entity| entity.eval_bonus_record_list());
        crate::BonusRecordListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct PayrollCalculationListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::PayrollCalculation>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> PayrollCalculationListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::PayrollCalculation>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::PayrollCalculation>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::PayrollCalculation>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::PayrollCalculation> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::PayrollCalculationExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::PayrollCalculationExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::PayrollCalculationExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::PayrollCalculationExpression::new(next, self.root_desc.clone())
    }
}