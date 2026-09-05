
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/address_record
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
#[teaql(entity = "AddressRecord", table = "address_record_data", data_service = "sqlite")]
pub struct AddressRecord {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:161
    street_address: String,

// @source moving-company.xml:161
    city_name: String,

// @source moving-company.xml:161
    postal_code: i64,

// @source moving-company.xml:161
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:161
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:161
#[teaql(column = "company")]
    company_id: u64,
// @source moving-company.xml:161
#[teaql(relation(target = "Company", local_key = "company_id", foreign_key = "id"))]
    company: Option<crate::Company>,
#[teaql(relation(target = "MoveOrder", local_key = "id", foreign_key = "origin_address_id", many))]
    move_order_list_as_origin_address: SmartList<crate::MoveOrder>,
#[teaql(relation(target = "MoveOrder", local_key = "id", foreign_key = "dest_address_id", many))]
    move_order_list_as_dest_address: SmartList<crate::MoveOrder>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl AddressRecord {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            street_address: String::new(),
            city_name: String::new(),
            postal_code: 0_i64,
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            company_id: 0_u64,
            company: None,
            move_order_list_as_origin_address: Default::default(),
            move_order_list_as_dest_address: Default::default(),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("AddressRecord", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.company {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.move_order_list_as_origin_address {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.move_order_list_as_dest_address {
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

    pub fn street_address(&self) -> String {
        self.changed_street_address().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.street_address.clone())
    }

    pub fn update_street_address(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.street_address = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.street_address.clone());
        self.root.set(self.entity_key(), "street_address", value);
        self
    }

    pub fn changed_street_address(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "street_address")
    }

    pub fn eval_street_address(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("street_address") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "street_address".to_string(), attempted_path: "street_address".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.street_address())
                }}

    pub fn city_name(&self) -> String {
        self.changed_city_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.city_name.clone())
    }

    pub fn update_city_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.city_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.city_name.clone());
        self.root.set(self.entity_key(), "city_name", value);
        self
    }

    pub fn changed_city_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "city_name")
    }

    pub fn eval_city_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("city_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "city_name".to_string(), attempted_path: "city_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.city_name())
                }}

    pub fn postal_code(&self) -> i64 {
        self.changed_postal_code().and_then(|value| value.try_i64()).map(|value| value as i64).unwrap_or(self.postal_code)
    }

    pub fn update_postal_code(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.postal_code = value.try_i64().map(|value| value as i64).unwrap_or(self.postal_code.clone());
        self.root.set(self.entity_key(), "postal_code", value);
        self
    }

    pub fn changed_postal_code(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "postal_code")
    }

    pub fn eval_postal_code(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("postal_code") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "postal_code".to_string(), attempted_path: "postal_code".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.postal_code())
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
    pub fn move_order_list_as_origin_address(&self) -> &SmartList<crate::MoveOrder> {
        &self.move_order_list_as_origin_address
    }

    pub fn move_order_list_as_origin_address_mut(&mut self) -> &mut SmartList<crate::MoveOrder> {
        &mut self.move_order_list_as_origin_address
    }

    pub fn eval_move_order_list_as_origin_address(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::MoveOrder>> {
        if !self.is_loaded("move_order_list_as_origin_address") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_order_list_as_origin_address".to_string(), attempted_path: "move_order_list_as_origin_address".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.move_order_list_as_origin_address)
        }
    }

    pub fn move_order_list_as_dest_address(&self) -> &SmartList<crate::MoveOrder> {
        &self.move_order_list_as_dest_address
    }

    pub fn move_order_list_as_dest_address_mut(&mut self) -> &mut SmartList<crate::MoveOrder> {
        &mut self.move_order_list_as_dest_address
    }

    pub fn eval_move_order_list_as_dest_address(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::MoveOrder>> {
        if !self.is_loaded("move_order_list_as_dest_address") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_order_list_as_dest_address".to_string(), attempted_path: "move_order_list_as_dest_address".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.move_order_list_as_dest_address)
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

