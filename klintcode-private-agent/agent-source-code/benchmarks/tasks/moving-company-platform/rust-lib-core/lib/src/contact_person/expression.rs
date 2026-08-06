#[derive(Clone)]
pub struct ContactPersonExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::ContactPerson>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> ContactPersonExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::ContactPerson>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::ContactPerson> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::ContactPerson> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::ContactPerson {
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

    pub fn get_phone_number(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("phone_number", |entity| entity.eval_phone_number());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_email_address(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("email_address", |entity| entity.eval_email_address());
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
    pub fn get_customer_profile_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("customer_profile_id", |entity| entity.eval_customer_profile_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_customer_profile(self) -> crate::CustomerProfileExpression<'a> {
        let next = self.result.and_then("customer_profile", |entity| entity.eval_customer_profile());
        crate::CustomerProfileExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct ContactPersonListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::ContactPerson>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> ContactPersonListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::ContactPerson>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::ContactPerson>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::ContactPerson>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::ContactPerson> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::ContactPersonExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::ContactPersonExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::ContactPersonExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::ContactPersonExpression::new(next, self.root_desc.clone())
    }
}