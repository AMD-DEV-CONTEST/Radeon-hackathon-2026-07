
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/inventory_tracking
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "InventoryTracking", table = "inventory_tracking_data", data_service = "sqlite")]
pub struct InventoryTracking {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:318
    location_name: String,

// @source moving-company.xml:318
    check_date: chrono::NaiveDate,

// @source moving-company.xml:318
    create_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:318
#[teaql(column = "equipment_item")]
    equipment_item_id: u64,
// @source moving-company.xml:318
#[teaql(relation(target = "EquipmentItem", local_key = "equipment_item_id", foreign_key = "id"))]
    equipment_item: Option<crate::EquipmentItem>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl InventoryTracking {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            location_name: String::new(),
            check_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: chrono::Utc::now(),
            version: 0_i64,
            equipment_item_id: 0_u64,
            equipment_item: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("InventoryTracking", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.equipment_item {
            entity.attach_root_recursive(root.clone());
        }
    }

    pub fn is_loaded(&self, field_or_relation: &str) -> bool {
        self.__load_state.is_loaded(field_or_relation)
    }

    pub fn set_load_state(&mut self, state: teaql_core::eval::LoadState) {
        self.__load_state = state;
    }

    pub fn id(&self) -> u64 {
        self.changed_id().and_then(|value| value.try_u64()).unwrap_or(self.id)
    }

    pub fn update_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.id = value.try_u64().unwrap_or(self.id.clone());
        self.root.set(self.entity_key(), "id", value);
        self
    }

    pub fn changed_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "id")
    }

    pub fn eval_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "id".to_string(), attempted_path: "id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.id())
                }}

    pub fn location_name(&self) -> String {
        self.changed_location_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.location_name.clone())
    }

    pub fn update_location_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.location_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.location_name.clone());
        self.root.set(self.entity_key(), "location_name", value);
        self
    }

    pub fn changed_location_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "location_name")
    }

    pub fn eval_location_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("location_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "location_name".to_string(), attempted_path: "location_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.location_name())
                }}

    pub fn check_date(&self) -> chrono::NaiveDate {
        self.changed_check_date().and_then(|value| value.try_date()).unwrap_or(self.check_date)
    }

    pub fn update_check_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.check_date = value.try_date().unwrap_or(self.check_date.clone());
        self.root.set(self.entity_key(), "check_date", value);
        self
    }

    pub fn changed_check_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "check_date")
    }

    pub fn eval_check_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("check_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "check_date".to_string(), attempted_path: "check_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.check_date())
                }}

    pub fn create_time(&self) -> chrono::DateTime<chrono::Utc> {
        self.changed_create_time().and_then(|value| value.try_timestamp()).unwrap_or(self.create_time)
    }

    pub fn update_create_time(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.create_time = value.try_timestamp().unwrap_or(self.create_time.clone());
        self.root.set(self.entity_key(), "create_time", value);
        self
    }

    pub fn changed_create_time(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "create_time")
    }

    pub fn eval_create_time(&self) -> teaql_core::eval::EvalResult<chrono::DateTime<chrono::Utc>> {
        if !self.is_loaded("create_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "create_time".to_string(), attempted_path: "create_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.create_time())
                }}

    pub fn version(&self) -> i64 {
        self.changed_version().and_then(|value| value.try_i64()).unwrap_or(self.version)
    }

    pub fn update_version(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.version = value.try_i64().unwrap_or(self.version.clone());
        self.root.set(self.entity_key(), "version", value);
        self
    }

    pub fn changed_version(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "version")
    }

    pub fn eval_version(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("version") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "version".to_string(), attempted_path: "version".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.version())
                }}
    pub fn equipment_item_id(&self) -> u64 {
        self.changed_equipment_item_id().and_then(|value| value.try_u64()).unwrap_or(self.equipment_item_id)
    }

    pub fn update_equipment_item_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.equipment_item_id = value.try_u64().unwrap_or(self.equipment_item_id.clone());
        self.root.set(self.entity_key(), "equipment_item_id", value);
        self
    }

    pub fn changed_equipment_item_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "equipment_item_id")
    }

    pub fn eval_equipment_item_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("equipment_item_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "equipment_item_id".to_string(), attempted_path: "equipment_item_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.equipment_item_id())
                }}
    pub fn equipment_item(&self) -> Option<&crate::EquipmentItem> {
        self.equipment_item.as_ref()
    }

    pub fn eval_equipment_item(&self) -> teaql_core::eval::EvalResult<&crate::EquipmentItem> {
        if !self.is_loaded("equipment_item") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "equipment_item".to_string(), attempted_path: "equipment_item".to_string() }
        } else {
            match &self.equipment_item {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn mark_as_delete(&mut self) -> &mut Self {
        self.root.mark_as_delete(self.entity_key());
        self
    }

    pub fn set_comment(&mut self, comment: impl Into<String>) -> &mut Self {
        self.root.set_comment(comment);
        self
    }
}

