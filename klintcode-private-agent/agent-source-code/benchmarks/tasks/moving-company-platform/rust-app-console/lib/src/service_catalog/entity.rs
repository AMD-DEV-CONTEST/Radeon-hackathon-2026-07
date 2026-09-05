
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/service_catalog
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
#[teaql(entity = "ServiceCatalog", table = "service_catalog_data", data_service = "sqlite")]
pub struct ServiceCatalog {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:327
    service_name: String,

// @source moving-company.xml:327
    service_description: String,

// @source moving-company.xml:327
    create_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:327
#[teaql(column = "company_profile")]
    company_profile_id: u64,
// @source moving-company.xml:327
#[teaql(relation(target = "CompanyProfile", local_key = "company_profile_id", foreign_key = "id"))]
    company_profile: Option<crate::CompanyProfile>,
#[teaql(relation(target = "ServiceConfig", local_key = "id", foreign_key = "service_catalog_id", many))]
    service_config_list: SmartList<crate::ServiceConfig>,
#[teaql(relation(target = "BoxRental", local_key = "id", foreign_key = "service_catalog_id", many))]
    box_rental_list: SmartList<crate::BoxRental>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl ServiceCatalog {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            service_name: String::new(),
            service_description: String::new(),
            create_time: chrono::Utc::now(),
            version: 0_i64,
            company_profile_id: 0_u64,
            company_profile: None,
            service_config_list: Default::default(),
            box_rental_list: Default::default(),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("ServiceCatalog", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.company_profile {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.service_config_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.box_rental_list {
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

    pub fn service_name(&self) -> String {
        self.changed_service_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.service_name.clone())
    }

    pub fn update_service_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.service_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.service_name.clone());
        self.root.set(self.entity_key(), "service_name", value);
        self
    }

    pub fn changed_service_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "service_name")
    }

    pub fn eval_service_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("service_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_name".to_string(), attempted_path: "service_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.service_name())
                }}

    pub fn service_description(&self) -> String {
        self.changed_service_description().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.service_description.clone())
    }

    pub fn update_service_description(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.service_description = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.service_description.clone());
        self.root.set(self.entity_key(), "service_description", value);
        self
    }

    pub fn changed_service_description(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "service_description")
    }

    pub fn eval_service_description(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("service_description") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_description".to_string(), attempted_path: "service_description".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.service_description())
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
    pub fn service_config_list(&self) -> &SmartList<crate::ServiceConfig> {
        &self.service_config_list
    }

    pub fn service_config_list_mut(&mut self) -> &mut SmartList<crate::ServiceConfig> {
        &mut self.service_config_list
    }

    pub fn eval_service_config_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ServiceConfig>> {
        if !self.is_loaded("service_config_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_config_list".to_string(), attempted_path: "service_config_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.service_config_list)
        }
    }

    pub fn box_rental_list(&self) -> &SmartList<crate::BoxRental> {
        &self.box_rental_list
    }

    pub fn box_rental_list_mut(&mut self) -> &mut SmartList<crate::BoxRental> {
        &mut self.box_rental_list
    }

    pub fn eval_box_rental_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::BoxRental>> {
        if !self.is_loaded("box_rental_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "box_rental_list".to_string(), attempted_path: "box_rental_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.box_rental_list)
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

