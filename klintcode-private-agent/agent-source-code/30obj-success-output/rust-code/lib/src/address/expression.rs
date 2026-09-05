#[derive(Clone)]
pub struct AddressExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::Address>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> AddressExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::Address>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::Address> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::Address> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::Address {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_street(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("street", |entity| entity.eval_street());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_city(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("city", |entity| entity.eval_city());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_state(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("state", |entity| entity.eval_state());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_postal_code(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("postal_code", |entity| entity.eval_postal_code());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_country(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("country", |entity| entity.eval_country());
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
    pub fn get_moving_event_list_as_origin_address(self) -> crate::MovingEventListExpression<'a> {
        let next = self.result.and_then("moving_event_list_as_origin_address", |entity| entity.eval_moving_event_list_as_origin_address());
        crate::MovingEventListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_moving_event_list_as_destination_address(self) -> crate::MovingEventListExpression<'a> {
        let next = self.result.and_then("moving_event_list_as_destination_address", |entity| entity.eval_moving_event_list_as_destination_address());
        crate::MovingEventListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_route_list_as_origin(self) -> crate::RouteListExpression<'a> {
        let next = self.result.and_then("route_list_as_origin", |entity| entity.eval_route_list_as_origin());
        crate::RouteListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_route_list_as_destination(self) -> crate::RouteListExpression<'a> {
        let next = self.result.and_then("route_list_as_destination", |entity| entity.eval_route_list_as_destination());
        crate::RouteListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct AddressListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Address>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> AddressListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Address>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::Address>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::Address>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::Address> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::AddressExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::AddressExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::AddressExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::AddressExpression::new(next, self.root_desc.clone())
    }
}