#[derive(Clone)]
pub struct LocationAddressExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::LocationAddress>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> LocationAddressExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::LocationAddress>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::LocationAddress> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::LocationAddress> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::LocationAddress {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_street_line(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("street_line", |entity| entity.eval_street_line());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_city_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("city_name", |entity| entity.eval_city_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_postal_code(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("postal_code", |entity| entity.eval_postal_code());
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
    pub fn get_company_profile_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("company_profile_id", |entity| entity.eval_company_profile_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company_profile(self) -> crate::CompanyProfileExpression<'a> {
        let next = self.result.and_then("company_profile", |entity| entity.eval_company_profile());
        crate::CompanyProfileExpression::new(next, self.root_desc.clone())
    }
    pub fn get_move_order_list_as_origin_address(self) -> crate::MoveOrderListExpression<'a> {
        let next = self.result.and_then("move_order_list_as_origin_address", |entity| entity.eval_move_order_list_as_origin_address());
        crate::MoveOrderListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_move_order_list_as_destination_address(self) -> crate::MoveOrderListExpression<'a> {
        let next = self.result.and_then("move_order_list_as_destination_address", |entity| entity.eval_move_order_list_as_destination_address());
        crate::MoveOrderListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct LocationAddressListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::LocationAddress>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> LocationAddressListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::LocationAddress>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::LocationAddress>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::LocationAddress>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::LocationAddress> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::LocationAddressExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::LocationAddressExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::LocationAddressExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::LocationAddressExpression::new(next, self.root_desc.clone())
    }
}