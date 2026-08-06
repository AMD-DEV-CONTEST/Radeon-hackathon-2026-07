
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/audit_log
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "AuditLog", table = "audit_log_data", data_service = "sqlite")]
pub struct AuditLog {
#[teaql(id)]
    id: u64,

// @source administration.xml:76
    log_timestamp: teaql_core::time::Timestamp,

// @source administration.xml:76
    action_type: String,

// @source administration.xml:76
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source administration.xml:76
#[teaql(column = "action_operator")]
    action_operator_id: u64,

// @source administration.xml:76
#[teaql(column = "entity_reference")]
    entity_reference_id: u64,
// @source administration.xml:76
#[teaql(relation(target = "UserAccount", local_key = "action_operator_id", foreign_key = "id"))]
    action_operator: Option<crate::UserAccount>,

// @source administration.xml:76
#[teaql(relation(target = "MoveOrder", local_key = "entity_reference_id", foreign_key = "id"))]
    entity_reference: Option<crate::MoveOrder>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl AuditLog {
    pub const ENTITY_NAME: &'static str = "Audit Log";

    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            log_timestamp: teaql_core::time::Timestamp::now(),
            action_type: String::new(),
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            action_operator_id: 0_u64,
            entity_reference_id: 0_u64,
            action_operator: None,
            entity_reference: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("AuditLog", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.action_operator {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.entity_reference {
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

    pub fn log_timestamp(&self) -> teaql_core::time::Timestamp {
        self.changed_log_timestamp().and_then(|value| value.try_timestamp()).unwrap_or(self.log_timestamp)
    }

    pub fn update_log_timestamp(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.log_timestamp = value.try_timestamp().unwrap_or(self.log_timestamp.clone());
        self.root.set(self.entity_key(), "log_timestamp", value);
        self
    }

    pub fn changed_log_timestamp(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "log_timestamp")
    }

    pub fn eval_log_timestamp(&self) -> teaql_core::eval::EvalResult<teaql_core::time::Timestamp> {
        if !self.is_loaded("log_timestamp") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "log_timestamp".to_string(), attempted_path: "log_timestamp".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.log_timestamp())
                }}

    pub fn action_type(&self) -> String {
        self.changed_action_type().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.action_type.clone())
    }

    pub fn update_action_type(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.action_type = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.action_type.clone());
        self.root.set(self.entity_key(), "action_type", value);
        self
    }

    pub fn changed_action_type(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "action_type")
    }

    pub fn eval_action_type(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("action_type") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "action_type".to_string(), attempted_path: "action_type".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.action_type())
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
    pub fn action_operator_id(&self) -> u64 {
        self.changed_action_operator_id().and_then(|value| value.try_u64()).unwrap_or(self.action_operator_id)
    }

    pub fn update_action_operator_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.action_operator_id = value.try_u64().unwrap_or(self.action_operator_id.clone());
        self.root.set(self.entity_key(), "action_operator_id", value);
        self
    }

    pub fn changed_action_operator_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "action_operator_id")
    }

    pub fn eval_action_operator_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("action_operator_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "action_operator_id".to_string(), attempted_path: "action_operator_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.action_operator_id())
                }}

    pub fn entity_reference_id(&self) -> u64 {
        self.changed_entity_reference_id().and_then(|value| value.try_u64()).unwrap_or(self.entity_reference_id)
    }

    pub fn update_entity_reference_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.entity_reference_id = value.try_u64().unwrap_or(self.entity_reference_id.clone());
        self.root.set(self.entity_key(), "entity_reference_id", value);
        self
    }

    pub fn changed_entity_reference_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "entity_reference_id")
    }

    pub fn eval_entity_reference_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("entity_reference_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "entity_reference_id".to_string(), attempted_path: "entity_reference_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.entity_reference_id())
                }}
    pub fn action_operator(&self) -> Option<&crate::UserAccount> {
        self.action_operator.as_ref()
    }

    pub fn eval_action_operator(&self) -> teaql_core::eval::EvalResult<&crate::UserAccount> {
        if !self.is_loaded("action_operator") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "action_operator".to_string(), attempted_path: "action_operator".to_string() }
        } else {
            match &self.action_operator {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn entity_reference(&self) -> Option<&crate::MoveOrder> {
        self.entity_reference.as_ref()
    }

    pub fn eval_entity_reference(&self) -> teaql_core::eval::EvalResult<&crate::MoveOrder> {
        if !self.is_loaded("entity_reference") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "entity_reference".to_string(), attempted_path: "entity_reference".to_string() }
        } else {
            match &self.entity_reference {
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

