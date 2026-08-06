
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/billing_info
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "BillingInfo", table = "billing_info_data", data_service = "sqlite", audit_mask_fields = "tax_id")]
pub struct BillingInfo {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:184
    billing_address: String,

// @source moving-company.xml:184
    tax_id: String,

// @source moving-company.xml:184
    create_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:184
#[teaql(column = "customer_profile")]
    customer_profile_id: u64,
// @source moving-company.xml:184
#[teaql(relation(target = "CustomerProfile", local_key = "customer_profile_id", foreign_key = "id"))]
    customer_profile: Option<crate::CustomerProfile>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl BillingInfo {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            billing_address: String::new(),
            tax_id: String::new(),
            create_time: chrono::Utc::now(),
            version: 0_i64,
            customer_profile_id: 0_u64,
            customer_profile: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("BillingInfo", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.customer_profile {
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

    pub fn billing_address(&self) -> String {
        self.changed_billing_address().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.billing_address.clone())
    }

    pub fn update_billing_address(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.billing_address = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.billing_address.clone());
        self.root.set(self.entity_key(), "billing_address", value);
        self
    }

    pub fn changed_billing_address(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "billing_address")
    }

    pub fn eval_billing_address(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("billing_address") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "billing_address".to_string(), attempted_path: "billing_address".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.billing_address())
                }}

    pub fn tax_id(&self) -> String {
        self.changed_tax_id().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.tax_id.clone())
    }

    pub fn update_tax_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.tax_id = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.tax_id.clone());
        self.root.set(self.entity_key(), "tax_id", value);
        self
    }

    pub fn changed_tax_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "tax_id")
    }

    pub fn eval_tax_id(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("tax_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "tax_id".to_string(), attempted_path: "tax_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.tax_id())
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
    pub fn customer_profile_id(&self) -> u64 {
        self.changed_customer_profile_id().and_then(|value| value.try_u64()).unwrap_or(self.customer_profile_id)
    }

    pub fn update_customer_profile_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.customer_profile_id = value.try_u64().unwrap_or(self.customer_profile_id.clone());
        self.root.set(self.entity_key(), "customer_profile_id", value);
        self
    }

    pub fn changed_customer_profile_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "customer_profile_id")
    }

    pub fn eval_customer_profile_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("customer_profile_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "customer_profile_id".to_string(), attempted_path: "customer_profile_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.customer_profile_id())
                }}
    pub fn customer_profile(&self) -> Option<&crate::CustomerProfile> {
        self.customer_profile.as_ref()
    }

    pub fn eval_customer_profile(&self) -> teaql_core::eval::EvalResult<&crate::CustomerProfile> {
        if !self.is_loaded("customer_profile") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "customer_profile".to_string(), attempted_path: "customer_profile".to_string() }
        } else {
            match &self.customer_profile {
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

