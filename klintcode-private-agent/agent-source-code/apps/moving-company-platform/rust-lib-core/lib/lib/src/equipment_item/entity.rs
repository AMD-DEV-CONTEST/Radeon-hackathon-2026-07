
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/equipment_item
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "EquipmentItem", table = "equipment_item_data", data_service = "sqlite")]
pub struct EquipmentItem {
#[teaql(id)]
    id: u64,

// @source assets.xml:42
    item_name: String,

// @source assets.xml:42
    serial_number: String,

// @source assets.xml:42
    purchase_date: chrono::NaiveDate,

// @source assets.xml:42
    condition: String,

// @source assets.xml:42
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source assets.xml:42
#[teaql(column = "company_profile")]
    company_profile_id: u64,
// @source assets.xml:42
#[teaql(relation(target = "CompanyProfile", local_key = "company_profile_id", foreign_key = "id"))]
    company_profile: Option<crate::CompanyProfile>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl EquipmentItem {
    pub const ENTITY_NAME: &'static str = "Equipment Item";

    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            item_name: String::new(),
            serial_number: String::new(),
            purchase_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            condition: String::new(),
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            company_profile_id: 0_u64,
            company_profile: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("EquipmentItem", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.company_profile {
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

    pub fn item_name(&self) -> String {
        self.changed_item_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.item_name.clone())
    }

    pub fn update_item_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.item_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.item_name.clone());
        self.root.set(self.entity_key(), "item_name", value);
        self
    }

    pub fn changed_item_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "item_name")
    }

    pub fn eval_item_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("item_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "item_name".to_string(), attempted_path: "item_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.item_name())
                }}

    pub fn serial_number(&self) -> String {
        self.changed_serial_number().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.serial_number.clone())
    }

    pub fn update_serial_number(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.serial_number = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.serial_number.clone());
        self.root.set(self.entity_key(), "serial_number", value);
        self
    }

    pub fn changed_serial_number(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "serial_number")
    }

    pub fn eval_serial_number(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("serial_number") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "serial_number".to_string(), attempted_path: "serial_number".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.serial_number())
                }}

    pub fn purchase_date(&self) -> chrono::NaiveDate {
        self.changed_purchase_date().and_then(|value| value.try_date()).unwrap_or(self.purchase_date)
    }

    pub fn update_purchase_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.purchase_date = value.try_date().unwrap_or(self.purchase_date.clone());
        self.root.set(self.entity_key(), "purchase_date", value);
        self
    }

    pub fn changed_purchase_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "purchase_date")
    }

    pub fn eval_purchase_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("purchase_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "purchase_date".to_string(), attempted_path: "purchase_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.purchase_date())
                }}

    pub fn condition(&self) -> String {
        self.changed_condition().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.condition.clone())
    }

    pub fn update_condition(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.condition = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.condition.clone());
        self.root.set(self.entity_key(), "condition", value);
        self
    }

    pub fn changed_condition(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "condition")
    }

    pub fn eval_condition(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("condition") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "condition".to_string(), attempted_path: "condition".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.condition())
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
    pub fn company_profile_id(&self) -> u64 {
        self.changed_company_profile_id().and_then(|value| value.try_u64()).unwrap_or(self.company_profile_id)
    }

    pub fn update_company_profile_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.company_profile_id = value.try_u64().unwrap_or(self.company_profile_id.clone());
        self.root.set(self.entity_key(), "company_profile_id", value);
        self
    }

    pub fn changed_company_profile_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "company_profile_id")
    }

    pub fn eval_company_profile_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("company_profile_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "company_profile_id".to_string(), attempted_path: "company_profile_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.company_profile_id())
                }}
    pub fn company_profile(&self) -> Option<&crate::CompanyProfile> {
        self.company_profile.as_ref()
    }

    pub fn eval_company_profile(&self) -> teaql_core::eval::EvalResult<&crate::CompanyProfile> {
        if !self.is_loaded("company_profile") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "company_profile".to_string(), attempted_path: "company_profile".to_string() }
        } else {
            match &self.company_profile {
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

