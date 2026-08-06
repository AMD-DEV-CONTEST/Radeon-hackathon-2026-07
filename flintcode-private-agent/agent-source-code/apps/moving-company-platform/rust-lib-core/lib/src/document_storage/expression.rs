#[derive(Clone)]
pub struct DocumentStorageExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::DocumentStorage>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> DocumentStorageExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::DocumentStorage>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::DocumentStorage> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::DocumentStorage> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::DocumentStorage {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_document_url(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("document_url", |entity| entity.eval_document_url());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_document_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("document_name", |entity| entity.eval_document_name());
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
pub struct DocumentStorageListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::DocumentStorage>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> DocumentStorageListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::DocumentStorage>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::DocumentStorage>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::DocumentStorage>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::DocumentStorage> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::DocumentStorageExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::DocumentStorageExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::DocumentStorageExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::DocumentStorageExpression::new(next, self.root_desc.clone())
    }
}