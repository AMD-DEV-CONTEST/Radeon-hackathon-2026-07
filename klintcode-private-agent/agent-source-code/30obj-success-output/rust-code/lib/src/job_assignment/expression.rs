#[derive(Clone)]
pub struct JobAssignmentExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::JobAssignment>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> JobAssignmentExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::JobAssignment>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::JobAssignment> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::JobAssignment> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::JobAssignment {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_assignment_id(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("assignment_id", |entity| entity.eval_assignment_id());
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

    pub fn get_role_on_job(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("role_on_job", |entity| entity.eval_role_on_job());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_status(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("status", |entity| entity.eval_status());
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

    pub fn get_moving_event_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("moving_event_id", |entity| entity.eval_moving_event_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_staff(self) -> crate::StaffExpression<'a> {
        let next = self.result.and_then("staff", |entity| entity.eval_staff());
        crate::StaffExpression::new(next, self.root_desc.clone())
    }

    pub fn get_moving_event(self) -> crate::MovingEventExpression<'a> {
        let next = self.result.and_then("moving_event", |entity| entity.eval_moving_event());
        crate::MovingEventExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct JobAssignmentListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::JobAssignment>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> JobAssignmentListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::JobAssignment>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::JobAssignment>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::JobAssignment>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::JobAssignment> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::JobAssignmentExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::JobAssignmentExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::JobAssignmentExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::JobAssignmentExpression::new(next, self.root_desc.clone())
    }
}