// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/user
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
#[teaql(entity = "User", table = "user_data", data_service = "sqlite", audit_mask_fields = "password_hash")]
pub struct User {
#[teaql(id)]
    id: u64,

// @source platform_modules.xml:19
    username: String,

// @source platform_modules.xml:19
    email: String,

// @source platform_modules.xml:19
    password_hash: String,

// @source platform_modules.xml:19
    create_time: chrono::DateTime<chrono::Utc>,

// @source platform_modules.xml:19
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
#[teaql(relation(target = "UserRole", local_key = "id", foreign_key = "user_id", many))]
    user_role_list: SmartList<crate::UserRole>,
#[teaql(relation(target = "AuthenticationLog", local_key = "id", foreign_key = "user_id", many))]
    authentication_log_list: SmartList<crate::AuthenticationLog>,
#[teaql(relation(target = "ActivityLog", local_key = "id", foreign_key = "user_id", many))]
    activity_log_list: SmartList<crate::ActivityLog>,
#[teaql(relation(target = "Notification", local_key = "id", foreign_key = "recipient_id", many))]
    notification_list: SmartList<crate::Notification>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl User {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            username: String::new(),
            email: String::new(),
            password_hash: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            user_role_list: Default::default(),
            authentication_log_list: Default::default(),
            activity_log_list: Default::default(),
            notification_list: Default::default(),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("User", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        for entity in &mut self.user_role_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.authentication_log_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.activity_log_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.notification_list {
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

    pub fn username(&self) -> String {
        self.changed_username().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.username.clone())
    }

    pub fn update_username(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.username = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.username.clone());
        self.root.set(self.entity_key(), "username", value);
        self
    }

    pub fn changed_username(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "username")
    }

    pub fn eval_username(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("username") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "username".to_string(), attempted_path: "username".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.username())
                }}

    pub fn email(&self) -> String {
        self.changed_email().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.email.clone())
    }

    pub fn update_email(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.email = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.email.clone());
        self.root.set(self.entity_key(), "email", value);
        self
    }

    pub fn changed_email(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "email")
    }

    pub fn eval_email(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("email") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "email".to_string(), attempted_path: "email".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.email())
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
    pub fn user_role_list(&self) -> &SmartList<crate::UserRole> {
        &self.user_role_list
    }

    pub fn user_role_list_mut(&mut self) -> &mut SmartList<crate::UserRole> {
        &mut self.user_role_list
    }

    pub fn eval_user_role_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::UserRole>> {
        if !self.is_loaded("user_role_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "user_role_list".to_string(), attempted_path: "user_role_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.user_role_list)
        }
    }

    pub fn authentication_log_list(&self) -> &SmartList<crate::AuthenticationLog> {
        &self.authentication_log_list
    }

    pub fn authentication_log_list_mut(&mut self) -> &mut SmartList<crate::AuthenticationLog> {
        &mut self.authentication_log_list
    }

    pub fn eval_authentication_log_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::AuthenticationLog>> {
        if !self.is_loaded("authentication_log_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "authentication_log_list".to_string(), attempted_path: "authentication_log_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.authentication_log_list)
        }
    }

    pub fn activity_log_list(&self) -> &SmartList<crate::ActivityLog> {
        &self.activity_log_list
    }

    pub fn activity_log_list_mut(&mut self) -> &mut SmartList<crate::ActivityLog> {
        &mut self.activity_log_list
    }

    pub fn eval_activity_log_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ActivityLog>> {
        if !self.is_loaded("activity_log_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "activity_log_list".to_string(), attempted_path: "activity_log_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.activity_log_list)
        }
    }

    pub fn notification_list(&self) -> &SmartList<crate::Notification> {
        &self.notification_list
    }

    pub fn notification_list_mut(&mut self) -> &mut SmartList<crate::Notification> {
        &mut self.notification_list
    }

    pub fn eval_notification_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::Notification>> {
        if !self.is_loaded("notification_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "notification_list".to_string(), attempted_path: "notification_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.notification_list)
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

    pub(crate) async fn save<'a, C>(
        &self,
        ctx: &'a C,
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::UserRepository<'a>>>
    where
        C: crate::TeaqlRepositoryProvider + ?Sized,
    {
        let root = ctx.user_context().entity_root();
        let key = self.entity_key();
        let has_ledger_change = (self.id != 0)
            && (root.current_change_set().changes().contains_key(&key)
                || root.is_marked_as_delete(&key)
                || root.is_new(&key));
        let repository = ctx
            .user_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("User"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

