#[derive(Clone)]
pub struct UserExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::User>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> UserExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::User>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::User> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::User> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::User {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_username(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("username", |entity| entity.eval_username());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_email(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("email", |entity| entity.eval_email());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_password_hash(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("password_hash", |entity| entity.eval_password_hash());
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
    pub fn get_user_role_list(self) -> crate::UserRoleListExpression<'a> {
        let next = self.result.and_then("user_role_list", |entity| entity.eval_user_role_list());
        crate::UserRoleListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_authentication_log_list(self) -> crate::AuthenticationLogListExpression<'a> {
        let next = self.result.and_then("authentication_log_list", |entity| entity.eval_authentication_log_list());
        crate::AuthenticationLogListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_activity_log_list(self) -> crate::ActivityLogListExpression<'a> {
        let next = self.result.and_then("activity_log_list", |entity| entity.eval_activity_log_list());
        crate::ActivityLogListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_notification_list(self) -> crate::NotificationListExpression<'a> {
        let next = self.result.and_then("notification_list", |entity| entity.eval_notification_list());
        crate::NotificationListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct UserListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::User>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> UserListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::User>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::User>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::User>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::User> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::UserExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::UserExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::UserExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::UserExpression::new(next, self.root_desc.clone())
    }
}