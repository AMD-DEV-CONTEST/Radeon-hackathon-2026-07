
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/role_definition
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
#[teaql(entity = "RoleDefinition", table = "role_definition_data", data_service = "sqlite")]
pub struct RoleDefinition {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:46
    role_name: String,

// @source moving-company.xml:46
    description_text: String,

// @source moving-company.xml:46
    create_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:46
#[teaql(column = "company_profile")]
    company_profile_id: u64,
// @source moving-company.xml:46
#[teaql(relation(target = "CompanyProfile", local_key = "company_profile_id", foreign_key = "id"))]
    company_profile: Option<crate::CompanyProfile>,
#[teaql(relation(target = "RoleAssignment", local_key = "id", foreign_key = "role_definition_id", many))]
    role_assignment_list: SmartList<crate::RoleAssignment>,
#[teaql(relation(target = "NotificationRule", local_key = "id", foreign_key = "role_definition_id", many))]
    notification_rule_list: SmartList<crate::NotificationRule>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl RoleDefinition {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            role_name: String::new(),
            description_text: String::new(),
            create_time: chrono::Utc::now(),
            version: 0_i64,
            company_profile_id: 0_u64,
            company_profile: None,
            role_assignment_list: Default::default(),
            notification_rule_list: Default::default(),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("RoleDefinition", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.company_profile {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.role_assignment_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.notification_rule_list {
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

    pub fn role_name(&self) -> String {
        self.changed_role_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.role_name.clone())
    }

    pub fn update_role_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.role_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.role_name.clone());
        self.root.set(self.entity_key(), "role_name", value);
        self
    }

    pub fn changed_role_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "role_name")
    }

    pub fn eval_role_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("role_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "role_name".to_string(), attempted_path: "role_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.role_name())
                }}

    pub fn description_text(&self) -> String {
        self.changed_description_text().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.description_text.clone())
    }

    pub fn update_description_text(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.description_text = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.description_text.clone());
        self.root.set(self.entity_key(), "description_text", value);
        self
    }

    pub fn changed_description_text(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "description_text")
    }

    pub fn eval_description_text(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("description_text") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "description_text".to_string(), attempted_path: "description_text".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.description_text())
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
    pub fn role_assignment_list(&self) -> &SmartList<crate::RoleAssignment> {
        &self.role_assignment_list
    }

    pub fn role_assignment_list_mut(&mut self) -> &mut SmartList<crate::RoleAssignment> {
        &mut self.role_assignment_list
    }

    pub fn eval_role_assignment_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::RoleAssignment>> {
        if !self.is_loaded("role_assignment_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "role_assignment_list".to_string(), attempted_path: "role_assignment_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.role_assignment_list)
        }
    }

    pub fn notification_rule_list(&self) -> &SmartList<crate::NotificationRule> {
        &self.notification_rule_list
    }

    pub fn notification_rule_list_mut(&mut self) -> &mut SmartList<crate::NotificationRule> {
        &mut self.notification_rule_list
    }

    pub fn eval_notification_rule_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::NotificationRule>> {
        if !self.is_loaded("notification_rule_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "notification_rule_list".to_string(), attempted_path: "notification_rule_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.notification_rule_list)
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

