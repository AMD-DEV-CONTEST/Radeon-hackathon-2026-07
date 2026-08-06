#[derive(Clone)]
pub struct FleetVehicleExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::FleetVehicle>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> FleetVehicleExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::FleetVehicle>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::FleetVehicle> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::FleetVehicle> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::FleetVehicle {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_vehicle_registration(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("vehicle_registration", |entity| entity.eval_vehicle_registration());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_vehicle_model(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("vehicle_model", |entity| entity.eval_vehicle_model());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_capacity_tons(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("capacity_tons", |entity| entity.eval_capacity_tons());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_mileage(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("mileage", |entity| entity.eval_mileage());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, teaql_core::time::Timestamp> {
        let next = self.result.and_then("create_time", |entity| entity.eval_create_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_update_time(self) -> crate::ValueExpression<'a, teaql_core::time::Timestamp> {
        let next = self.result.and_then("update_time", |entity| entity.eval_update_time());
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

    pub fn get_vehicle_type_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("vehicle_type_id", |entity| entity.eval_vehicle_type_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company_profile(self) -> crate::CompanyProfileExpression<'a> {
        let next = self.result.and_then("company_profile", |entity| entity.eval_company_profile());
        crate::CompanyProfileExpression::new(next, self.root_desc.clone())
    }

    pub fn get_vehicle_type(self) -> crate::VehicleTypeExpression<'a> {
        let next = self.result.and_then("vehicle_type", |entity| entity.eval_vehicle_type());
        crate::VehicleTypeExpression::new(next, self.root_desc.clone())
    }
    pub fn vehicle_type_is_small_van(self) -> crate::ValueExpression<'a, bool> {
        let next = self.result.and_then("vehicle_type_id", |entity| {
            if !entity.is_loaded("vehicle_type_id") {
                teaql_core::eval::EvalResult::NotLoaded { failed_node: "vehicle_type_id".to_string(), attempted_path: "vehicle_type_id".to_string() }
            } else {
                teaql_core::eval::EvalResult::Value(entity.vehicle_type_is_small_van())
            }
        });
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn vehicle_type_is_medium_truck(self) -> crate::ValueExpression<'a, bool> {
        let next = self.result.and_then("vehicle_type_id", |entity| {
            if !entity.is_loaded("vehicle_type_id") {
                teaql_core::eval::EvalResult::NotLoaded { failed_node: "vehicle_type_id".to_string(), attempted_path: "vehicle_type_id".to_string() }
            } else {
                teaql_core::eval::EvalResult::Value(entity.vehicle_type_is_medium_truck())
            }
        });
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn vehicle_type_is_large_truck(self) -> crate::ValueExpression<'a, bool> {
        let next = self.result.and_then("vehicle_type_id", |entity| {
            if !entity.is_loaded("vehicle_type_id") {
                teaql_core::eval::EvalResult::NotLoaded { failed_node: "vehicle_type_id".to_string(), attempted_path: "vehicle_type_id".to_string() }
            } else {
                teaql_core::eval::EvalResult::Value(entity.vehicle_type_is_large_truck())
            }
        });
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_maintenance_schedule_list(self) -> crate::MaintenanceScheduleListExpression<'a> {
        let next = self.result.and_then("maintenance_schedule_list", |entity| entity.eval_maintenance_schedule_list());
        crate::MaintenanceScheduleListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_fuel_log_list(self) -> crate::FuelLogListExpression<'a> {
        let next = self.result.and_then("fuel_log_list", |entity| entity.eval_fuel_log_list());
        crate::FuelLogListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct FleetVehicleListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::FleetVehicle>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> FleetVehicleListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::FleetVehicle>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::FleetVehicle>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::FleetVehicle>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::FleetVehicle> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::FleetVehicleExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::FleetVehicleExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::FleetVehicleExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::FleetVehicleExpression::new(next, self.root_desc.clone())
    }
}