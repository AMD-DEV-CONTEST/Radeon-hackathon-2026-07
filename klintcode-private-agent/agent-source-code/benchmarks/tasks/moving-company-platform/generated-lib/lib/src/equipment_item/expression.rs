#[derive(Clone)]
pub struct EquipmentItemExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::EquipmentItem>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> EquipmentItemExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::EquipmentItem>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::EquipmentItem> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::EquipmentItem> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::EquipmentItem {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_item_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("item_name", |entity| entity.eval_item_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_serial_number(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("serial_number", |entity| entity.eval_serial_number());
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
    pub fn get_asset_vehicle_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("asset_vehicle_id", |entity| entity.eval_asset_vehicle_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_asset_vehicle(self) -> crate::FleetVehicleExpression<'a> {
        let next = self.result.and_then("asset_vehicle", |entity| entity.eval_asset_vehicle());
        crate::FleetVehicleExpression::new(next, self.root_desc.clone())
    }
    pub fn get_inventory_tracking_list(self) -> crate::InventoryTrackingListExpression<'a> {
        let next = self.result.and_then("inventory_tracking_list", |entity| entity.eval_inventory_tracking_list());
        crate::InventoryTrackingListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct EquipmentItemListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::EquipmentItem>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> EquipmentItemListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::EquipmentItem>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::EquipmentItem>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::EquipmentItem>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::EquipmentItem> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::EquipmentItemExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::EquipmentItemExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::EquipmentItemExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::EquipmentItemExpression::new(next, self.root_desc.clone())
    }
}