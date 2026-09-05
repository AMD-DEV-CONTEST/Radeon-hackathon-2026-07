
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/maintenance_schedule
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "MaintenanceSchedule", table = "maintenance_schedule_data", data_service = "sqlite")]
pub struct MaintenanceSchedule {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:310
    maintenance_type: String,

// @source moving-company.xml:310
    scheduled_date: chrono::NaiveDate,

// @source moving-company.xml:310
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:310
#[teaql(column = "asset_vehicle")]
    asset_vehicle_id: u64,
// @source moving-company.xml:310
#[teaql(relation(target = "FleetVehicle", local_key = "asset_vehicle_id", foreign_key = "id"))]
    asset_vehicle: Option<crate::FleetVehicle>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl MaintenanceSchedule {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            maintenance_type: String::new(),
            scheduled_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            asset_vehicle_id: 0_u64,
            asset_vehicle: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("MaintenanceSchedule", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.asset_vehicle {
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

    pub fn maintenance_type(&self) -> String {
        self.changed_maintenance_type().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.maintenance_type.clone())
    }

    pub fn update_maintenance_type(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.maintenance_type = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.maintenance_type.clone());
        self.root.set(self.entity_key(), "maintenance_type", value);
        self
    }

    pub fn changed_maintenance_type(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "maintenance_type")
    }

    pub fn eval_maintenance_type(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("maintenance_type") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "maintenance_type".to_string(), attempted_path: "maintenance_type".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.maintenance_type())
                }}

    pub fn scheduled_date(&self) -> chrono::NaiveDate {
        self.changed_scheduled_date().and_then(|value| value.try_date()).unwrap_or(self.scheduled_date)
    }

    pub fn update_scheduled_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.scheduled_date = value.try_date().unwrap_or(self.scheduled_date.clone());
        self.root.set(self.entity_key(), "scheduled_date", value);
        self
    }

    pub fn changed_scheduled_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "scheduled_date")
    }

    pub fn eval_scheduled_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("scheduled_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "scheduled_date".to_string(), attempted_path: "scheduled_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.scheduled_date())
                }}

    pub fn create_time(&self) -> teaql_core::time::Timestamp {
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

    pub fn eval_create_time(&self) -> teaql_core::eval::EvalResult<teaql_core::time::Timestamp> {
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
    pub fn asset_vehicle_id(&self) -> u64 {
        self.changed_asset_vehicle_id().and_then(|value| value.try_u64()).unwrap_or(self.asset_vehicle_id)
    }

    pub fn update_asset_vehicle_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.asset_vehicle_id = value.try_u64().unwrap_or(self.asset_vehicle_id.clone());
        self.root.set(self.entity_key(), "asset_vehicle_id", value);
        self
    }

    pub fn changed_asset_vehicle_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "asset_vehicle_id")
    }

    pub fn eval_asset_vehicle_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("asset_vehicle_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "asset_vehicle_id".to_string(), attempted_path: "asset_vehicle_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.asset_vehicle_id())
                }}
    pub fn asset_vehicle(&self) -> Option<&crate::FleetVehicle> {
        self.asset_vehicle.as_ref()
    }

    pub fn eval_asset_vehicle(&self) -> teaql_core::eval::EvalResult<&crate::FleetVehicle> {
        if !self.is_loaded("asset_vehicle") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "asset_vehicle".to_string(), attempted_path: "asset_vehicle".to_string() }
        } else {
            match &self.asset_vehicle {
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

