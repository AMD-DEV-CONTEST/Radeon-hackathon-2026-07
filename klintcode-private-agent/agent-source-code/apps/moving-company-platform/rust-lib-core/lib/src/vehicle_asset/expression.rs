#[derive(Clone)]
pub struct VehicleAssetExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::VehicleAsset>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> VehicleAssetExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::VehicleAsset>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::VehicleAsset> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::VehicleAsset> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::VehicleAsset {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_license_plate(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("license_plate", |entity| entity.eval_license_plate());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_vehicle_model(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("vehicle_model", |entity| entity.eval_vehicle_model());
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
    pub fn get_company_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("company_id", |entity| entity.eval_company_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company(self) -> crate::CompanyExpression<'a> {
        let next = self.result.and_then("company", |entity| entity.eval_company());
        crate::CompanyExpression::new(next, self.root_desc.clone())
    }
    pub fn get_equipment_item_list(self) -> crate::EquipmentItemListExpression<'a> {
        let next = self.result.and_then("equipment_item_list", |entity| entity.eval_equipment_item_list());
        crate::EquipmentItemListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_maintenance_schedule_list(self) -> crate::MaintenanceScheduleListExpression<'a> {
        let next = self.result.and_then("maintenance_schedule_list", |entity| entity.eval_maintenance_schedule_list());
        crate::MaintenanceScheduleListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_insurance_policy_list(self) -> crate::InsurancePolicyListExpression<'a> {
        let next = self.result.and_then("insurance_policy_list", |entity| entity.eval_insurance_policy_list());
        crate::InsurancePolicyListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_move_order_list(self) -> crate::MoveOrderListExpression<'a> {
        let next = self.result.and_then("move_order_list", |entity| entity.eval_move_order_list());
        crate::MoveOrderListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct VehicleAssetListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::VehicleAsset>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> VehicleAssetListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::VehicleAsset>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::VehicleAsset>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::VehicleAsset>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::VehicleAsset> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::VehicleAssetExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::VehicleAssetExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::VehicleAssetExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::VehicleAssetExpression::new(next, self.root_desc.clone())
    }
}