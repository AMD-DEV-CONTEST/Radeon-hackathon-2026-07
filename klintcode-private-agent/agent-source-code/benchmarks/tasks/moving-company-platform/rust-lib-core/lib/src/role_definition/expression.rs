#[derive(Clone)]
pub struct RoleDefinitionExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::RoleDefinition>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> RoleDefinitionExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::RoleDefinition>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::RoleDefinition> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::RoleDefinition> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::RoleDefinition {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_role_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("role_name", |entity| entity.eval_role_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_description_text(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("description_text", |entity| entity.eval_description_text());
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
    pub fn get_company_profile_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("company_profile_id", |entity| entity.eval_company_profile_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company_profile(self) -> crate::CompanyProfileExpression<'a> {
        let next = self.result.and_then("company_profile", |entity| entity.eval_company_profile());
        crate::CompanyProfileExpression::new(next, self.root_desc.clone())
    }
    pub fn get_role_assignment_list(self) -> crate::RoleAssignmentListExpression<'a> {
        let next = self.result.and_then("role_assignment_list", |entity| entity.eval_role_assignment_list());
        crate::RoleAssignmentListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_notification_rule_list(self) -> crate::NotificationRuleListExpression<'a> {
        let next = self.result.and_then("notification_rule_list", |entity| entity.eval_notification_rule_list());
        crate::NotificationRuleListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct RoleDefinitionListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::RoleDefinition>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> RoleDefinitionListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::RoleDefinition>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::RoleDefinition>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::RoleDefinition>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::RoleDefinition> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::RoleDefinitionExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::RoleDefinitionExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::RoleDefinitionExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::RoleDefinitionExpression::new(next, self.root_desc.clone())
    }
}