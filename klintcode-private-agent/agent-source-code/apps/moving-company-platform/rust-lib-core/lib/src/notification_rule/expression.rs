#[derive(Clone)]
pub struct NotificationRuleExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::NotificationRule>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> NotificationRuleExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::NotificationRule>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::NotificationRule> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::NotificationRule> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::NotificationRule {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_rule_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("rule_name", |entity| entity.eval_rule_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_is_active(self) -> crate::ValueExpression<'a, bool> {
        let next = self.result.and_then("is_active", |entity| entity.eval_is_active());
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
}

#[derive(Clone)]
pub struct NotificationRuleListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::NotificationRule>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> NotificationRuleListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::NotificationRule>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::NotificationRule>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::NotificationRule>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::NotificationRule> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::NotificationRuleExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::NotificationRuleExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::NotificationRuleExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::NotificationRuleExpression::new(next, self.root_desc.clone())
    }
}