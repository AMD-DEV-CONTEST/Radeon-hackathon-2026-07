
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/role_assignment
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "RoleAssignment", table = "role_assignment_data", data_service = "sqlite")]
pub struct RoleAssignment {
#[teaql(id)]
    id: u64,

// @source administration.xml:65
    assign_date: chrono::NaiveDate,

// @source administration.xml:65
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source administration.xml:65
#[teaql(column = "user_account")]
    user_account_id: u64,

// @source administration.xml:65
#[teaql(column = "role_definition")]
    role_definition_id: u64,
// @source administration.xml:65
#[teaql(relation(target = "UserAccount", local_key = "user_account_id", foreign_key = "id"))]
    user_account: Option<crate::UserAccount>,

// @source administration.xml:65
#[teaql(relation(target = "RoleDefinition", local_key = "role_definition_id", foreign_key = "id"))]
    role_definition: Option<crate::RoleDefinition>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl RoleAssignment {
    pub const ENTITY_NAME: &'static str = "Role Assignment";

    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            assign_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            user_account_id: 0_u64,
            role_definition_id: 0_u64,
            user_account: None,
            role_definition: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("RoleAssignment", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.user_account {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.role_definition {
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

    pub fn assign_date(&self) -> chrono::NaiveDate {
        self.changed_assign_date().and_then(|value| value.try_date()).unwrap_or(self.assign_date)
    }

    pub fn update_assign_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.assign_date = value.try_date().unwrap_or(self.assign_date.clone());
        self.root.set(self.entity_key(), "assign_date", value);
        self
    }

    pub fn changed_assign_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "assign_date")
    }

    pub fn eval_assign_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("assign_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "assign_date".to_string(), attempted_path: "assign_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.assign_date())
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
    pub fn user_account_id(&self) -> u64 {
        self.changed_user_account_id().and_then(|value| value.try_u64()).unwrap_or(self.user_account_id)
    }

    pub fn update_user_account_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.user_account_id = value.try_u64().unwrap_or(self.user_account_id.clone());
        self.root.set(self.entity_key(), "user_account_id", value);
        self
    }

    pub fn changed_user_account_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "user_account_id")
    }

    pub fn eval_user_account_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("user_account_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "user_account_id".to_string(), attempted_path: "user_account_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.user_account_id())
                }}

    pub fn role_definition_id(&self) -> u64 {
        self.changed_role_definition_id().and_then(|value| value.try_u64()).unwrap_or(self.role_definition_id)
    }

    pub fn update_role_definition_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.role_definition_id = value.try_u64().unwrap_or(self.role_definition_id.clone());
        self.root.set(self.entity_key(), "role_definition_id", value);
        self
    }

    pub fn changed_role_definition_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "role_definition_id")
    }

    pub fn eval_role_definition_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("role_definition_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "role_definition_id".to_string(), attempted_path: "role_definition_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.role_definition_id())
                }}
    pub fn user_account(&self) -> Option<&crate::UserAccount> {
        self.user_account.as_ref()
    }

    pub fn eval_user_account(&self) -> teaql_core::eval::EvalResult<&crate::UserAccount> {
        if !self.is_loaded("user_account") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "user_account".to_string(), attempted_path: "user_account".to_string() }
        } else {
            match &self.user_account {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn role_definition(&self) -> Option<&crate::RoleDefinition> {
        self.role_definition.as_ref()
    }

    pub fn eval_role_definition(&self) -> teaql_core::eval::EvalResult<&crate::RoleDefinition> {
        if !self.is_loaded("role_definition") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "role_definition".to_string(), attempted_path: "role_definition".to_string() }
        } else {
            match &self.role_definition {
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

