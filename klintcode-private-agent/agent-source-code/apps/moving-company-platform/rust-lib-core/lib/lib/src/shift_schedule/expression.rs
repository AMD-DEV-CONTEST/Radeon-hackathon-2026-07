#[derive(Clone)]
pub struct ShiftScheduleExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::ShiftSchedule>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> ShiftScheduleExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::ShiftSchedule>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::ShiftSchedule> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::ShiftSchedule> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::ShiftSchedule {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_shift_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("shift_date", |entity| entity.eval_shift_date());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_start_time(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("start_time", |entity| entity.eval_start_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_end_time(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("end_time", |entity| entity.eval_end_time());
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
    pub fn get_employee_record_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("employee_record_id", |entity| entity.eval_employee_record_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_employee_record(self) -> crate::EmployeeRegistryExpression<'a> {
        let next = self.result.and_then("employee_record", |entity| entity.eval_employee_record());
        crate::EmployeeRegistryExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct ShiftScheduleListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::ShiftSchedule>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> ShiftScheduleListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::ShiftSchedule>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::ShiftSchedule>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::ShiftSchedule>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::ShiftSchedule> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::ShiftScheduleExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::ShiftScheduleExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::ShiftScheduleExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::ShiftScheduleExpression::new(next, self.root_desc.clone())
    }
}