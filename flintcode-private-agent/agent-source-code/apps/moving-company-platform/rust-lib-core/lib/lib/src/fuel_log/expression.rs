#[derive(Clone)]
pub struct FuelLogExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::FuelLog>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> FuelLogExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::FuelLog>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::FuelLog> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::FuelLog> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::FuelLog {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_fuel_amount(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("fuel_amount", |entity| entity.eval_fuel_amount());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_fuel_cost(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("fuel_cost", |entity| entity.eval_fuel_cost());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_fuel_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("fuel_date", |entity| entity.eval_fuel_date());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_odometer_reading(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("odometer_reading", |entity| entity.eval_odometer_reading());
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
    pub fn get_asset_vehicle_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("asset_vehicle_id", |entity| entity.eval_asset_vehicle_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_asset_vehicle(self) -> crate::FleetVehicleExpression<'a> {
        let next = self.result.and_then("asset_vehicle", |entity| entity.eval_asset_vehicle());
        crate::FleetVehicleExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct FuelLogListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::FuelLog>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> FuelLogListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::FuelLog>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::FuelLog>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::FuelLog>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::FuelLog> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::FuelLogExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::FuelLogExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::FuelLogExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::FuelLogExpression::new(next, self.root_desc.clone())
    }
}