#[derive(Clone)]
pub struct LinkedContactExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::LinkedContact>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> LinkedContactExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::LinkedContact>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::LinkedContact> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::LinkedContact> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::LinkedContact {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_contact_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("contact_name", |entity| entity.eval_contact_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_contact_email(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("contact_email", |entity| entity.eval_contact_email());
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
    pub fn get_corporate_customer_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("corporate_customer_id", |entity| entity.eval_corporate_customer_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_corporate_customer(self) -> crate::CorporateCustomerExpression<'a> {
        let next = self.result.and_then("corporate_customer", |entity| entity.eval_corporate_customer());
        crate::CorporateCustomerExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct LinkedContactListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::LinkedContact>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> LinkedContactListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::LinkedContact>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::LinkedContact>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::LinkedContact>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::LinkedContact> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::LinkedContactExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::LinkedContactExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::LinkedContactExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::LinkedContactExpression::new(next, self.root_desc.clone())
    }
}