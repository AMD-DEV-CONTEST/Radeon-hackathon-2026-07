
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/user_account
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
#[teaql(entity = "UserAccount", table = "user_account_data", data_service = "sqlite", audit_mask_fields = "password_hash,email_address,account_name")]
pub struct UserAccount {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:38
    account_name: String,

// @source moving-company.xml:38
    email_address: String,

// @source moving-company.xml:38
    password_hash: String,

// @source moving-company.xml:38
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:38
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:38
#[teaql(column = "company_profile")]
    company_profile_id: u64,

// @source moving-company.xml:38
#[teaql(column = "employee_registry")]
    employee_registry_id: u64,
// @source moving-company.xml:38
#[teaql(relation(target = "CompanyProfile", local_key = "company_profile_id", foreign_key = "id"))]
    company_profile: Option<crate::CompanyProfile>,

// @source moving-company.xml:38
#[teaql(relation(target = "EmployeeRegistry", local_key = "employee_registry_id", foreign_key = "id"))]
    employee_registry: Option<crate::EmployeeRegistry>,
#[teaql(relation(target = "RoleAssignment", local_key = "id", foreign_key = "user_account_id", many))]
    role_assignment_list: SmartList<crate::RoleAssignment>,
#[teaql(relation(target = "AuditLog", local_key = "id", foreign_key = "action_operator_id", many))]
    audit_log_list: SmartList<crate::AuditLog>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl UserAccount {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            account_name: String::new(),
            email_address: String::new(),
            password_hash: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            company_profile_id: 0_u64,
            employee_registry_id: 0_u64,
            company_profile: None,
            employee_registry: None,
            role_assignment_list: Default::default(),
            audit_log_list: Default::default(),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("UserAccount", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.company_profile {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.employee_registry {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.role_assignment_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.audit_log_list {
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

    pub fn account_name(&self) -> String {
        self.changed_account_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.account_name.clone())
    }

    pub fn update_account_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.account_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.account_name.clone());
        self.root.set(self.entity_key(), "account_name", value);
        self
    }

    pub fn changed_account_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "account_name")
    }

    pub fn eval_account_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("account_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "account_name".to_string(), attempted_path: "account_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.account_name())
                }}

    pub fn email_address(&self) -> String {
        self.changed_email_address().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.email_address.clone())
    }

    pub fn update_email_address(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.email_address = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.email_address.clone());
        self.root.set(self.entity_key(), "email_address", value);
        self
    }

    pub fn changed_email_address(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "email_address")
    }

    pub fn eval_email_address(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("email_address") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "email_address".to_string(), attempted_path: "email_address".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.email_address())
                }}

    pub fn password_hash(&self) -> String {
        self.changed_password_hash().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.password_hash.clone())
    }

    pub fn update_password_hash(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.password_hash = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.password_hash.clone());
        self.root.set(self.entity_key(), "password_hash", value);
        self
    }

    pub fn changed_password_hash(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "password_hash")
    }

    pub fn eval_password_hash(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("password_hash") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "password_hash".to_string(), attempted_path: "password_hash".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.password_hash())
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

    pub fn employee_registry_id(&self) -> u64 {
        self.changed_employee_registry_id().and_then(|value| value.try_u64()).unwrap_or(self.employee_registry_id)
    }

    pub fn update_employee_registry_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.employee_registry_id = value.try_u64().unwrap_or(self.employee_registry_id.clone());
        self.root.set(self.entity_key(), "employee_registry_id", value);
        self
    }

    pub fn changed_employee_registry_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "employee_registry_id")
    }

    pub fn eval_employee_registry_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("employee_registry_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "employee_registry_id".to_string(), attempted_path: "employee_registry_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.employee_registry_id())
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

    pub fn employee_registry(&self) -> Option<&crate::EmployeeRegistry> {
        self.employee_registry.as_ref()
    }

    pub fn eval_employee_registry(&self) -> teaql_core::eval::EvalResult<&crate::EmployeeRegistry> {
        if !self.is_loaded("employee_registry") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "employee_registry".to_string(), attempted_path: "employee_registry".to_string() }
        } else {
            match &self.employee_registry {
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

    pub fn audit_log_list(&self) -> &SmartList<crate::AuditLog> {
        &self.audit_log_list
    }

    pub fn audit_log_list_mut(&mut self) -> &mut SmartList<crate::AuditLog> {
        &mut self.audit_log_list
    }

    pub fn eval_audit_log_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::AuditLog>> {
        if !self.is_loaded("audit_log_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "audit_log_list".to_string(), attempted_path: "audit_log_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.audit_log_list)
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

