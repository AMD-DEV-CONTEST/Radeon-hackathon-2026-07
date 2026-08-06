#[derive(Clone)]
pub struct InsurancePolicyExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::InsurancePolicy>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> InsurancePolicyExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::InsurancePolicy>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::InsurancePolicy> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::InsurancePolicy> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::InsurancePolicy {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_policy_number(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("policy_number", |entity| entity.eval_policy_number());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_provider_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("provider_name", |entity| entity.eval_provider_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_expiry_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("expiry_date", |entity| entity.eval_expiry_date());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, teaql_core::time::Timestamp> {
        let next = self.result.and_then("create_time", |entity| entity.eval_create_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_version(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("version", |entity| entity.eval_version());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_fleet_vehicle_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("fleet_vehicle_id", |entity| entity.eval_fleet_vehicle_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_fleet_vehicle(self) -> crate::FleetVehicleExpression<'a> {
        let next = self.result.and_then("fleet_vehicle", |entity| entity.eval_fleet_vehicle());
        crate::FleetVehicleExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct InsurancePolicyListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::InsurancePolicy>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> InsurancePolicyListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::InsurancePolicy>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::InsurancePolicy>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::InsurancePolicy>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::InsurancePolicy> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::InsurancePolicyExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::InsurancePolicyExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::InsurancePolicyExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::InsurancePolicyExpression::new(next, self.root_desc.clone())
    }
}