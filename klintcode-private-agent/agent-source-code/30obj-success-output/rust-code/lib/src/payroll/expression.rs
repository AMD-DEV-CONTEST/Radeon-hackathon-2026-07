#[derive(Clone)]
pub struct PayrollExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::Payroll>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> PayrollExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::Payroll>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::Payroll> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::Payroll> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::Payroll {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_pay_period_start(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("pay_period_start", |entity| entity.eval_pay_period_start());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_pay_period_end(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("pay_period_end", |entity| entity.eval_pay_period_end());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_base_salary(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("base_salary", |entity| entity.eval_base_salary());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_overtime_pay(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("overtime_pay", |entity| entity.eval_overtime_pay());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_bonus(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("bonus", |entity| entity.eval_bonus());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_deductions(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("deductions", |entity| entity.eval_deductions());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_net_pay(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("net_pay", |entity| entity.eval_net_pay());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_payment_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("payment_date", |entity| entity.eval_payment_date());
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
    pub fn get_staff_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("staff_id", |entity| entity.eval_staff_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_staff(self) -> crate::StaffExpression<'a> {
        let next = self.result.and_then("staff", |entity| entity.eval_staff());
        crate::StaffExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct PayrollListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Payroll>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> PayrollListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Payroll>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::Payroll>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::Payroll>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::Payroll> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::PayrollExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::PayrollExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::PayrollExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::PayrollExpression::new(next, self.root_desc.clone())
    }
}