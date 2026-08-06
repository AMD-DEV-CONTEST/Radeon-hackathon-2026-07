#[derive(Clone)]
pub struct EmployeeRegistryExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::EmployeeRegistry>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> EmployeeRegistryExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::EmployeeRegistry>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::EmployeeRegistry> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::EmployeeRegistry> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::EmployeeRegistry {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_employee_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("employee_name", |entity| entity.eval_employee_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_job_title(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("job_title", |entity| entity.eval_job_title());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_hire_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("hire_date", |entity| entity.eval_hire_date());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, teaql_core::time::Timestamp> {
        let next = self.result.and_then("create_time", |entity| entity.eval_create_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_update_time(self) -> crate::ValueExpression<'a, teaql_core::time::Timestamp> {
        let next = self.result.and_then("update_time", |entity| entity.eval_update_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_version(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("version", |entity| entity.eval_version());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company_profile_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("company_profile_id", |entity| entity.eval_company_profile_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company_profile(self) -> crate::CompanyProfileExpression<'a> {
        let next = self.result.and_then("company_profile", |entity| entity.eval_company_profile());
        crate::CompanyProfileExpression::new(next, self.root_desc.clone())
    }
    pub fn get_user_account_list(self) -> crate::UserAccountListExpression<'a> {
        let next = self.result.and_then("user_account_list", |entity| entity.eval_user_account_list());
        crate::UserAccountListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_leave_request_list(self) -> crate::LeaveRequestListExpression<'a> {
        let next = self.result.and_then("leave_request_list", |entity| entity.eval_leave_request_list());
        crate::LeaveRequestListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_payroll_calculation_list(self) -> crate::PayrollCalculationListExpression<'a> {
        let next = self.result.and_then("payroll_calculation_list", |entity| entity.eval_payroll_calculation_list());
        crate::PayrollCalculationListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_bonus_record_list(self) -> crate::BonusRecordListExpression<'a> {
        let next = self.result.and_then("bonus_record_list", |entity| entity.eval_bonus_record_list());
        crate::BonusRecordListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_job_assignment_list(self) -> crate::JobAssignmentListExpression<'a> {
        let next = self.result.and_then("job_assignment_list", |entity| entity.eval_job_assignment_list());
        crate::JobAssignmentListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_worked_hours_list(self) -> crate::WorkedHoursListExpression<'a> {
        let next = self.result.and_then("worked_hours_list", |entity| entity.eval_worked_hours_list());
        crate::WorkedHoursListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_customer_profile_list(self) -> crate::CustomerProfileListExpression<'a> {
        let next = self.result.and_then("customer_profile_list", |entity| entity.eval_customer_profile_list());
        crate::CustomerProfileListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_interaction_history_list(self) -> crate::InteractionHistoryListExpression<'a> {
        let next = self.result.and_then("interaction_history_list", |entity| entity.eval_interaction_history_list());
        crate::InteractionHistoryListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct EmployeeRegistryListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::EmployeeRegistry>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> EmployeeRegistryListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::EmployeeRegistry>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::EmployeeRegistry>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::EmployeeRegistry>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::EmployeeRegistry> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::EmployeeRegistryExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::EmployeeRegistryExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::EmployeeRegistryExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::EmployeeRegistryExpression::new(next, self.root_desc.clone())
    }
}