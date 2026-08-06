#[derive(Clone)]
pub struct NotificationExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::Notification>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> NotificationExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::Notification>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::Notification> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::Notification> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::Notification {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_subject(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("subject", |entity| entity.eval_subject());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_body(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("body", |entity| entity.eval_body());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_notification_type(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("notification_type", |entity| entity.eval_notification_type());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_status(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("status", |entity| entity.eval_status());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_scheduled_time(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
        let next = self.result.and_then("scheduled_time", |entity| entity.eval_scheduled_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_sent_time(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
        let next = self.result.and_then("sent_time", |entity| entity.eval_sent_time());
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
    pub fn get_recipient_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("recipient_id", |entity| entity.eval_recipient_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_recipient(self) -> crate::UserExpression<'a> {
        let next = self.result.and_then("recipient", |entity| entity.eval_recipient());
        crate::UserExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct NotificationListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Notification>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> NotificationListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Notification>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::Notification>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::Notification>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::Notification> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::NotificationExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::NotificationExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::NotificationExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::NotificationExpression::new(next, self.root_desc.clone())
    }
}