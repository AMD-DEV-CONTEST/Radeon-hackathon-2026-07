
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/insurance_policy
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "InsurancePolicy", table = "insurance_policy_data", data_service = "sqlite")]
pub struct InsurancePolicy {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:98
    policy_number: String,

// @source moving-company.xml:98
    provider_name: String,

// @source moving-company.xml:98
    expiry_date: chrono::NaiveDate,

// @source moving-company.xml:98
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:98
#[teaql(column = "fleet_vehicle")]
    fleet_vehicle_id: u64,
// @source moving-company.xml:98
#[teaql(relation(target = "FleetVehicle", local_key = "fleet_vehicle_id", foreign_key = "id"))]
    fleet_vehicle: Option<crate::FleetVehicle>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl InsurancePolicy {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            policy_number: String::new(),
            provider_name: String::new(),
            expiry_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            fleet_vehicle_id: 0_u64,
            fleet_vehicle: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("InsurancePolicy", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.fleet_vehicle {
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

    pub fn policy_number(&self) -> String {
        self.changed_policy_number().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.policy_number.clone())
    }

    pub fn update_policy_number(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.policy_number = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.policy_number.clone());
        self.root.set(self.entity_key(), "policy_number", value);
        self
    }

    pub fn changed_policy_number(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "policy_number")
    }

    pub fn eval_policy_number(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("policy_number") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "policy_number".to_string(), attempted_path: "policy_number".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.policy_number())
                }}

    pub fn provider_name(&self) -> String {
        self.changed_provider_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.provider_name.clone())
    }

    pub fn update_provider_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.provider_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.provider_name.clone());
        self.root.set(self.entity_key(), "provider_name", value);
        self
    }

    pub fn changed_provider_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "provider_name")
    }

    pub fn eval_provider_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("provider_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "provider_name".to_string(), attempted_path: "provider_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.provider_name())
                }}

    pub fn expiry_date(&self) -> chrono::NaiveDate {
        self.changed_expiry_date().and_then(|value| value.try_date()).unwrap_or(self.expiry_date)
    }

    pub fn update_expiry_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.expiry_date = value.try_date().unwrap_or(self.expiry_date.clone());
        self.root.set(self.entity_key(), "expiry_date", value);
        self
    }

    pub fn changed_expiry_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "expiry_date")
    }

    pub fn eval_expiry_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("expiry_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "expiry_date".to_string(), attempted_path: "expiry_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.expiry_date())
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
    pub fn fleet_vehicle_id(&self) -> u64 {
        self.changed_fleet_vehicle_id().and_then(|value| value.try_u64()).unwrap_or(self.fleet_vehicle_id)
    }

    pub fn update_fleet_vehicle_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.fleet_vehicle_id = value.try_u64().unwrap_or(self.fleet_vehicle_id.clone());
        self.root.set(self.entity_key(), "fleet_vehicle_id", value);
        self
    }

    pub fn changed_fleet_vehicle_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "fleet_vehicle_id")
    }

    pub fn eval_fleet_vehicle_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("fleet_vehicle_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "fleet_vehicle_id".to_string(), attempted_path: "fleet_vehicle_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.fleet_vehicle_id())
                }}
    pub fn fleet_vehicle(&self) -> Option<&crate::FleetVehicle> {
        self.fleet_vehicle.as_ref()
    }

    pub fn eval_fleet_vehicle(&self) -> teaql_core::eval::EvalResult<&crate::FleetVehicle> {
        if !self.is_loaded("fleet_vehicle") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "fleet_vehicle".to_string(), attempted_path: "fleet_vehicle".to_string() }
        } else {
            match &self.fleet_vehicle {
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

