#[derive(Clone)]
pub struct RolePermissionExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::RolePermission>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> RolePermissionExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::RolePermission>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::RolePermission> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::RolePermission> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::RolePermission {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_granted_at(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
        let next = self.result.and_then("granted_at", |entity| entity.eval_granted_at());
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
    pub fn get_role_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("role_id", |entity| entity.eval_role_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_permission_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("permission_id", |entity| entity.eval_permission_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_role(self) -> crate::RoleExpression<'a> {
        let next = self.result.and_then("role", |entity| entity.eval_role());
        crate::RoleExpression::new(next, self.root_desc.clone())
    }

    pub fn get_permission(self) -> crate::PermissionExpression<'a> {
        let next = self.result.and_then("permission", |entity| entity.eval_permission());
        crate::PermissionExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct RolePermissionListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::RolePermission>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> RolePermissionListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::RolePermission>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::RolePermission>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::RolePermission>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::RolePermission> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::RolePermissionExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::RolePermissionExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::RolePermissionExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::RolePermissionExpression::new(next, self.root_desc.clone())
    }
}