#[derive(Clone)]
pub struct RoleAssignmentExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::RoleAssignment>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> RoleAssignmentExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::RoleAssignment>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::RoleAssignment> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::RoleAssignment> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::RoleAssignment {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_assign_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("assign_date", |entity| entity.eval_assign_date());
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
    pub fn get_user_account_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("user_account_id", |entity| entity.eval_user_account_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_role_definition_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("role_definition_id", |entity| entity.eval_role_definition_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_user_account(self) -> crate::UserAccountExpression<'a> {
        let next = self.result.and_then("user_account", |entity| entity.eval_user_account());
        crate::UserAccountExpression::new(next, self.root_desc.clone())
    }

    pub fn get_role_definition(self) -> crate::RoleDefinitionExpression<'a> {
        let next = self.result.and_then("role_definition", |entity| entity.eval_role_definition());
        crate::RoleDefinitionExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct RoleAssignmentListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::RoleAssignment>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> RoleAssignmentListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::RoleAssignment>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::RoleAssignment>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::RoleAssignment>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::RoleAssignment> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::RoleAssignmentExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::RoleAssignmentExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::RoleAssignmentExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::RoleAssignmentExpression::new(next, self.root_desc.clone())
    }
}