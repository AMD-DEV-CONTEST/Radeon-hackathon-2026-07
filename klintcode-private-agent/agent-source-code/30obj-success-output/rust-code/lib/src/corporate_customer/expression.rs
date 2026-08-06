#[derive(Clone)]
pub struct CorporateCustomerExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::CorporateCustomer>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CorporateCustomerExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::CorporateCustomer>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::CorporateCustomer> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::CorporateCustomer> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::CorporateCustomer {
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

    pub fn get_company_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("company_name", |entity| entity.eval_company_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_tax_id(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("tax_id", |entity| entity.eval_tax_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_contact_person(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("contact_person", |entity| entity.eval_contact_person());
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

    pub fn get_address(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("address", |entity| entity.eval_address());
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
    pub fn get_customer_contact_list(self) -> crate::CustomerContactListExpression<'a> {
        let next = self.result.and_then("customer_contact_list", |entity| entity.eval_customer_contact_list());
        crate::CustomerContactListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct CorporateCustomerListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::CorporateCustomer>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CorporateCustomerListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::CorporateCustomer>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::CorporateCustomer>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::CorporateCustomer>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::CorporateCustomer> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::CorporateCustomerExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CorporateCustomerExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::CorporateCustomerExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CorporateCustomerExpression::new(next, self.root_desc.clone())
    }
}