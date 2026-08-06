
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/service_config
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "ServiceConfig", table = "service_config_data", data_service = "sqlite")]
pub struct ServiceConfig {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:335
    config_name: String,

// @source moving-company.xml:335
    price_amount: rust_decimal::Decimal,

// @source moving-company.xml:335
    create_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:335
#[teaql(column = "service_catalog")]
    service_catalog_id: u64,
// @source moving-company.xml:335
#[teaql(relation(target = "ServiceCatalog", local_key = "service_catalog_id", foreign_key = "id"))]
    service_catalog: Option<crate::ServiceCatalog>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl ServiceConfig {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            config_name: String::new(),
            price_amount: rust_decimal::Decimal::ZERO,
            create_time: chrono::Utc::now(),
            version: 0_i64,
            service_catalog_id: 0_u64,
            service_catalog: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("ServiceConfig", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.service_catalog {
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

    pub fn config_name(&self) -> String {
        self.changed_config_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.config_name.clone())
    }

    pub fn update_config_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.config_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.config_name.clone());
        self.root.set(self.entity_key(), "config_name", value);
        self
    }

    pub fn changed_config_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "config_name")
    }

    pub fn eval_config_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("config_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "config_name".to_string(), attempted_path: "config_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.config_name())
                }}

    pub fn price_amount(&self) -> rust_decimal::Decimal {
        self.changed_price_amount().and_then(|value| value.try_decimal()).unwrap_or(self.price_amount)
    }

    pub fn update_price_amount(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.price_amount = value.try_decimal().unwrap_or(self.price_amount.clone());
        self.root.set(self.entity_key(), "price_amount", value);
        self
    }

    pub fn changed_price_amount(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "price_amount")
    }

    pub fn eval_price_amount(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("price_amount") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "price_amount".to_string(), attempted_path: "price_amount".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.price_amount())
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
    pub fn service_catalog_id(&self) -> u64 {
        self.changed_service_catalog_id().and_then(|value| value.try_u64()).unwrap_or(self.service_catalog_id)
    }

    pub fn update_service_catalog_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.service_catalog_id = value.try_u64().unwrap_or(self.service_catalog_id.clone());
        self.root.set(self.entity_key(), "service_catalog_id", value);
        self
    }

    pub fn changed_service_catalog_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "service_catalog_id")
    }

    pub fn eval_service_catalog_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("service_catalog_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_catalog_id".to_string(), attempted_path: "service_catalog_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.service_catalog_id())
                }}
    pub fn service_catalog(&self) -> Option<&crate::ServiceCatalog> {
        self.service_catalog.as_ref()
    }

    pub fn eval_service_catalog(&self) -> teaql_core::eval::EvalResult<&crate::ServiceCatalog> {
        if !self.is_loaded("service_catalog") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_catalog".to_string(), attempted_path: "service_catalog".to_string() }
        } else {
            match &self.service_catalog {
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

