#[derive(Clone)]
pub struct RouteExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::Route>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> RouteExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::Route>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::Route> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::Route> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::Route {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_route_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("route_name", |entity| entity.eval_route_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_distance_km(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("distance_km", |entity| entity.eval_distance_km());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_estimated_time_minutes(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("estimated_time_minutes", |entity| entity.eval_estimated_time_minutes());
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
    pub fn get_origin_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("origin_id", |entity| entity.eval_origin_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_destination_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("destination_id", |entity| entity.eval_destination_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_origin(self) -> crate::AddressExpression<'a> {
        let next = self.result.and_then("origin", |entity| entity.eval_origin());
        crate::AddressExpression::new(next, self.root_desc.clone())
    }

    pub fn get_destination(self) -> crate::AddressExpression<'a> {
        let next = self.result.and_then("destination", |entity| entity.eval_destination());
        crate::AddressExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct RouteListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Route>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> RouteListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Route>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::Route>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::Route>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::Route> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::RouteExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::RouteExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::RouteExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::RouteExpression::new(next, self.root_desc.clone())
    }
}