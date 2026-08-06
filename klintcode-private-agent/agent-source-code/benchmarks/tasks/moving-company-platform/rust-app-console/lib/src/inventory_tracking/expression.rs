#[derive(Clone)]
pub struct InventoryTrackingExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::InventoryTracking>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> InventoryTrackingExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::InventoryTracking>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::InventoryTracking> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::InventoryTracking> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::InventoryTracking {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_location_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("location_name", |entity| entity.eval_location_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_check_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("check_date", |entity| entity.eval_check_date());
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
    pub fn get_equipment_item_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("equipment_item_id", |entity| entity.eval_equipment_item_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_equipment_item(self) -> crate::EquipmentItemExpression<'a> {
        let next = self.result.and_then("equipment_item", |entity| entity.eval_equipment_item());
        crate::EquipmentItemExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct InventoryTrackingListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::InventoryTracking>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> InventoryTrackingListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::InventoryTracking>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::InventoryTracking>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::InventoryTracking>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::InventoryTracking> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::InventoryTrackingExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::InventoryTrackingExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::InventoryTrackingExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::InventoryTrackingExpression::new(next, self.root_desc.clone())
    }
}