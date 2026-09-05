#[derive(Clone)]
pub struct CustomerContactExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::CustomerContact>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CustomerContactExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::CustomerContact>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::CustomerContact> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::CustomerContact> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::CustomerContact {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("name", |entity| entity.eval_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_first_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("first_name", |entity| entity.eval_first_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_last_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("last_name", |entity| entity.eval_last_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_email(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("email", |entity| entity.eval_email());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_phone(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("phone", |entity| entity.eval_phone());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_relationship(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("relationship", |entity| entity.eval_relationship());
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
    pub fn get_private_customer_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("private_customer_id", |entity| entity.eval_private_customer_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_corporate_customer_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("corporate_customer_id", |entity| entity.eval_corporate_customer_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_private_customer(self) -> crate::PrivateCustomerExpression<'a> {
        let next = self.result.and_then("private_customer", |entity| entity.eval_private_customer());
        crate::PrivateCustomerExpression::new(next, self.root_desc.clone())
    }

    pub fn get_corporate_customer(self) -> crate::CorporateCustomerExpression<'a> {
        let next = self.result.and_then("corporate_customer", |entity| entity.eval_corporate_customer());
        crate::CorporateCustomerExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct CustomerContactListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::CustomerContact>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CustomerContactListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::CustomerContact>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::CustomerContact>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::CustomerContact>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::CustomerContact> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::CustomerContactExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CustomerContactExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::CustomerContactExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CustomerContactExpression::new(next, self.root_desc.clone())
    }
}