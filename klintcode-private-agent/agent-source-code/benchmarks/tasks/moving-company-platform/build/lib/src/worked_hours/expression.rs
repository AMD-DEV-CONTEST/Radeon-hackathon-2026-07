#[derive(Clone)]
pub struct WorkedHoursExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::WorkedHours>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> WorkedHoursExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::WorkedHours>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::WorkedHours> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::WorkedHours> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::WorkedHours {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_hours_logged(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("hours_logged", |entity| entity.eval_hours_logged());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_work_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("work_date", |entity| entity.eval_work_date());
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
    pub fn get_job_assignment_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("job_assignment_id", |entity| entity.eval_job_assignment_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_employee_record_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("employee_record_id", |entity| entity.eval_employee_record_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_job_assignment(self) -> crate::JobAssignmentExpression<'a> {
        let next = self.result.and_then("job_assignment", |entity| entity.eval_job_assignment());
        crate::JobAssignmentExpression::new(next, self.root_desc.clone())
    }

    pub fn get_employee_record(self) -> crate::EmployeeRegistryExpression<'a> {
        let next = self.result.and_then("employee_record", |entity| entity.eval_employee_record());
        crate::EmployeeRegistryExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct WorkedHoursListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::WorkedHours>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> WorkedHoursListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::WorkedHours>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::WorkedHours>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::WorkedHours>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::WorkedHours> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::WorkedHoursExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::WorkedHoursExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::WorkedHoursExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::WorkedHoursExpression::new(next, self.root_desc.clone())
    }
}