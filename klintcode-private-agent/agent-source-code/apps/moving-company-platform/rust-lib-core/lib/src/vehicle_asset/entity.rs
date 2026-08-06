
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/vehicle_asset
use std::collections::BTreeMap;

use teaql_core::SmartList;
use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "VehicleAsset", table = "vehicle_asset_data", data_service = "sqlite")]
pub struct VehicleAsset {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:123
    license_plate: String,

// @source moving-company.xml:123
    vehicle_model: String,

// @source moving-company.xml:123
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:123
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:123
#[teaql(column = "company")]
    company_id: u64,
// @source moving-company.xml:123
#[teaql(relation(target = "Company", local_key = "company_id", foreign_key = "id"))]
    company: Option<crate::Company>,
#[teaql(relation(target = "EquipmentItem", local_key = "id", foreign_key = "vehicle_asset_id", many))]
    equipment_item_list: SmartList<crate::EquipmentItem>,
#[teaql(relation(target = "MaintenanceSchedule", local_key = "id", foreign_key = "vehicle_asset_id", many))]
    maintenance_schedule_list: SmartList<crate::MaintenanceSchedule>,
#[teaql(relation(target = "InsurancePolicy", local_key = "id", foreign_key = "vehicle_asset_id", many))]
    insurance_policy_list: SmartList<crate::InsurancePolicy>,
#[teaql(relation(target = "MoveOrder", local_key = "id", foreign_key = "assigned_vehicle_id", many))]
    move_order_list: SmartList<crate::MoveOrder>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl VehicleAsset {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            license_plate: String::new(),
            vehicle_model: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            company_id: 0_u64,
            company: None,
            equipment_item_list: Default::default(),
            maintenance_schedule_list: Default::default(),
            insurance_policy_list: Default::default(),
            move_order_list: Default::default(),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("VehicleAsset", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.company {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.equipment_item_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.maintenance_schedule_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.insurance_policy_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.move_order_list {
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

    pub fn license_plate(&self) -> String {
        self.changed_license_plate().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.license_plate.clone())
    }

    pub fn update_license_plate(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.license_plate = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.license_plate.clone());
        self.root.set(self.entity_key(), "license_plate", value);
        self
    }

    pub fn changed_license_plate(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "license_plate")
    }

    pub fn eval_license_plate(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("license_plate") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "license_plate".to_string(), attempted_path: "license_plate".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.license_plate())
                }}

    pub fn vehicle_model(&self) -> String {
        self.changed_vehicle_model().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.vehicle_model.clone())
    }

    pub fn update_vehicle_model(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.vehicle_model = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.vehicle_model.clone());
        self.root.set(self.entity_key(), "vehicle_model", value);
        self
    }

    pub fn changed_vehicle_model(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "vehicle_model")
    }

    pub fn eval_vehicle_model(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("vehicle_model") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "vehicle_model".to_string(), attempted_path: "vehicle_model".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.vehicle_model())
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

    pub fn update_time(&self) -> chrono::DateTime<chrono::Utc> {
        self.changed_update_time().and_then(|value| value.try_timestamp()).unwrap_or(self.update_time)
    }

    pub fn update_update_time(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.update_time = value.try_timestamp().unwrap_or(self.update_time.clone());
        self.root.set(self.entity_key(), "update_time", value);
        self
    }

    pub fn changed_update_time(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "update_time")
    }

    pub fn eval_update_time(&self) -> teaql_core::eval::EvalResult<chrono::DateTime<chrono::Utc>> {
        if !self.is_loaded("update_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "update_time".to_string(), attempted_path: "update_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.update_time())
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
    pub fn company_id(&self) -> u64 {
        self.changed_company_id().and_then(|value| value.try_u64()).unwrap_or(self.company_id)
    }

    pub fn update_company_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.company_id = value.try_u64().unwrap_or(self.company_id.clone());
        self.root.set(self.entity_key(), "company_id", value);
        self
    }

    pub fn changed_company_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "company_id")
    }

    pub fn eval_company_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("company_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "company_id".to_string(), attempted_path: "company_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.company_id())
                }}
    pub fn company(&self) -> Option<&crate::Company> {
        self.company.as_ref()
    }

    pub fn eval_company(&self) -> teaql_core::eval::EvalResult<&crate::Company> {
        if !self.is_loaded("company") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "company".to_string(), attempted_path: "company".to_string() }
        } else {
            match &self.company {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }
    pub fn equipment_item_list(&self) -> &SmartList<crate::EquipmentItem> {
        &self.equipment_item_list
    }

    pub fn equipment_item_list_mut(&mut self) -> &mut SmartList<crate::EquipmentItem> {
        &mut self.equipment_item_list
    }

    pub fn eval_equipment_item_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::EquipmentItem>> {
        if !self.is_loaded("equipment_item_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "equipment_item_list".to_string(), attempted_path: "equipment_item_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.equipment_item_list)
        }
    }

    pub fn maintenance_schedule_list(&self) -> &SmartList<crate::MaintenanceSchedule> {
        &self.maintenance_schedule_list
    }

    pub fn maintenance_schedule_list_mut(&mut self) -> &mut SmartList<crate::MaintenanceSchedule> {
        &mut self.maintenance_schedule_list
    }

    pub fn eval_maintenance_schedule_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::MaintenanceSchedule>> {
        if !self.is_loaded("maintenance_schedule_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "maintenance_schedule_list".to_string(), attempted_path: "maintenance_schedule_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.maintenance_schedule_list)
        }
    }

    pub fn insurance_policy_list(&self) -> &SmartList<crate::InsurancePolicy> {
        &self.insurance_policy_list
    }

    pub fn insurance_policy_list_mut(&mut self) -> &mut SmartList<crate::InsurancePolicy> {
        &mut self.insurance_policy_list
    }

    pub fn eval_insurance_policy_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::InsurancePolicy>> {
        if !self.is_loaded("insurance_policy_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "insurance_policy_list".to_string(), attempted_path: "insurance_policy_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.insurance_policy_list)
        }
    }

    pub fn move_order_list(&self) -> &SmartList<crate::MoveOrder> {
        &self.move_order_list
    }

    pub fn move_order_list_mut(&mut self) -> &mut SmartList<crate::MoveOrder> {
        &mut self.move_order_list
    }

    pub fn eval_move_order_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::MoveOrder>> {
        if !self.is_loaded("move_order_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_order_list".to_string(), attempted_path: "move_order_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.move_order_list)
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

