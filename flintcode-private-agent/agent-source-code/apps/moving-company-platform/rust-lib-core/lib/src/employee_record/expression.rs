#[derive(Clone)]
pub struct EmployeeRecordExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::EmployeeRecord>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> EmployeeRecordExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::EmployeeRecord>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::EmployeeRecord> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::EmployeeRecord> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::EmployeeRecord {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_employee_number(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("employee_number", |entity| entity.eval_employee_number());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_hire_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("hire_date", |entity| entity.eval_hire_date());
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
    pub fn get_user_account_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("user_account_id", |entity| entity.eval_user_account_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_user_account(self) -> crate::UserAccountExpression<'a> {
        let next = self.result.and_then("user_account", |entity| entity.eval_user_account());
        crate::UserAccountExpression::new(next, self.root_desc.clone())
    }
    pub fn get_payroll_calculation_list(self) -> crate::PayrollCalculationListExpression<'a> {
        let next = self.result.and_then("payroll_calculation_list", |entity| entity.eval_payroll_calculation_list());
        crate::PayrollCalculationListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_worked_hours_list(self) -> crate::WorkedHoursListExpression<'a> {
        let next = self.result.and_then("worked_hours_list", |entity| entity.eval_worked_hours_list());
        crate::WorkedHoursListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_leave_request_list(self) -> crate::LeaveRequestListExpression<'a> {
        let next = self.result.and_then("leave_request_list", |entity| entity.eval_leave_request_list());
        crate::LeaveRequestListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_corporate_customer_list(self) -> crate::CorporateCustomerListExpression<'a> {
        let next = self.result.and_then("corporate_customer_list", |entity| entity.eval_corporate_customer_list());
        crate::CorporateCustomerListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_inventory_tracking_list(self) -> crate::InventoryTrackingListExpression<'a> {
        let next = self.result.and_then("inventory_tracking_list", |entity| entity.eval_inventory_tracking_list());
        crate::InventoryTrackingListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_job_assignment_list(self) -> crate::JobAssignmentListExpression<'a> {
        let next = self.result.and_then("job_assignment_list", |entity| entity.eval_job_assignment_list());
        crate::JobAssignmentListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_expense_record_list(self) -> crate::ExpenseRecordListExpression<'a> {
        let next = self.result.and_then("expense_record_list", |entity| entity.eval_expense_record_list());
        crate::ExpenseRecordListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_financial_summary_list(self) -> crate::FinancialSummaryListExpression<'a> {
        let next = self.result.and_then("financial_summary_list", |entity| entity.eval_financial_summary_list());
        crate::FinancialSummaryListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct EmployeeRecordListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::EmployeeRecord>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> EmployeeRecordListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::EmployeeRecord>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::EmployeeRecord>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::EmployeeRecord>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::EmployeeRecord> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::EmployeeRecordExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::EmployeeRecordExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::EmployeeRecordExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::EmployeeRecordExpression::new(next, self.root_desc.clone())
    }
}