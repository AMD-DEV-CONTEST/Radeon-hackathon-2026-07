#[derive(Clone)]
pub struct StaffExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::Staff>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> StaffExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::Staff>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::Staff> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::Staff> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::Staff {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_employee_id(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("employee_id", |entity| entity.eval_employee_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_first_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("first_name", |entity| entity.eval_first_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_last_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("last_name", |entity| entity.eval_last_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_email(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("email", |entity| entity.eval_email());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_phone(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("phone", |entity| entity.eval_phone());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_hire_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("hire_date", |entity| entity.eval_hire_date());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_job_title(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("job_title", |entity| entity.eval_job_title());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_department(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("department", |entity| entity.eval_department());
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
    pub fn get_job_assignment_list(self) -> crate::JobAssignmentListExpression<'a> {
        let next = self.result.and_then("job_assignment_list", |entity| entity.eval_job_assignment_list());
        crate::JobAssignmentListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_worked_hours_list(self) -> crate::WorkedHoursListExpression<'a> {
        let next = self.result.and_then("worked_hours_list", |entity| entity.eval_worked_hours_list());
        crate::WorkedHoursListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_payroll_list(self) -> crate::PayrollListExpression<'a> {
        let next = self.result.and_then("payroll_list", |entity| entity.eval_payroll_list());
        crate::PayrollListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_bonus_list(self) -> crate::BonusListExpression<'a> {
        let next = self.result.and_then("bonus_list", |entity| entity.eval_bonus_list());
        crate::BonusListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_leave_tracking_list(self) -> crate::LeaveTrackingListExpression<'a> {
        let next = self.result.and_then("leave_tracking_list", |entity| entity.eval_leave_tracking_list());
        crate::LeaveTrackingListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct StaffListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Staff>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> StaffListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Staff>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::Staff>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::Staff>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::Staff> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::StaffExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::StaffExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::StaffExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::StaffExpression::new(next, self.root_desc.clone())
    }
}