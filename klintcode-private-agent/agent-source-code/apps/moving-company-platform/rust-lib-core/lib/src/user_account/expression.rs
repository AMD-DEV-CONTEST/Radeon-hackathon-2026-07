#[derive(Clone)]
pub struct UserAccountExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::UserAccount>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> UserAccountExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::UserAccount>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::UserAccount> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::UserAccount> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::UserAccount {
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

    pub fn get_password_hash(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("password_hash", |entity| entity.eval_password_hash());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_mobile_phone(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("mobile_phone", |entity| entity.eval_mobile_phone());
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
    pub fn get_company_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("company_id", |entity| entity.eval_company_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company(self) -> crate::CompanyExpression<'a> {
        let next = self.result.and_then("company", |entity| entity.eval_company());
        crate::CompanyExpression::new(next, self.root_desc.clone())
    }
    pub fn get_user_role_list(self) -> crate::UserRoleListExpression<'a> {
        let next = self.result.and_then("user_role_list", |entity| entity.eval_user_role_list());
        crate::UserRoleListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_audit_log_list(self) -> crate::AuditLogListExpression<'a> {
        let next = self.result.and_then("audit_log_list", |entity| entity.eval_audit_log_list());
        crate::AuditLogListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_notification_rule_list(self) -> crate::NotificationRuleListExpression<'a> {
        let next = self.result.and_then("notification_rule_list", |entity| entity.eval_notification_rule_list());
        crate::NotificationRuleListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_document_storage_list(self) -> crate::DocumentStorageListExpression<'a> {
        let next = self.result.and_then("document_storage_list", |entity| entity.eval_document_storage_list());
        crate::DocumentStorageListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_employee_record_list(self) -> crate::EmployeeRecordListExpression<'a> {
        let next = self.result.and_then("employee_record_list", |entity| entity.eval_employee_record_list());
        crate::EmployeeRecordListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct UserAccountListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::UserAccount>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> UserAccountListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::UserAccount>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::UserAccount>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::UserAccount>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::UserAccount> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::UserAccountExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::UserAccountExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::UserAccountExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::UserAccountExpression::new(next, self.root_desc.clone())
    }
}