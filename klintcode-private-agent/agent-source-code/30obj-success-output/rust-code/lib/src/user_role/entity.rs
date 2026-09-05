// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/user_role
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "UserRole", table = "user_role_data", data_service = "sqlite")]
pub struct UserRole {
#[teaql(id)]
    id: u64,

// @source platform_modules.xml:44
    assigned_at: chrono::DateTime<chrono::Utc>,

// @source platform_modules.xml:44
    create_time: chrono::DateTime<chrono::Utc>,

// @source platform_modules.xml:44
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source platform_modules.xml:44
#[teaql(column = "\"user\"")]
    user_id: u64,

// @source platform_modules.xml:44
#[teaql(column = "role")]
    role_id: u64,
// @source platform_modules.xml:44
#[teaql(relation(target = "User", local_key = "user_id", foreign_key = "id"))]
    user: Option<crate::User>,

// @source platform_modules.xml:44
#[teaql(relation(target = "Role", local_key = "role_id", foreign_key = "id"))]
    role: Option<crate::Role>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl UserRole {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            assigned_at: chrono::Utc::now(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            user_id: 0_u64,
            role_id: 0_u64,
            user: None,
            role: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("UserRole", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.user {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.role {
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

    pub fn assigned_at(&self) -> chrono::DateTime<chrono::Utc> {
        self.changed_assigned_at().and_then(|value| value.try_timestamp()).unwrap_or(self.assigned_at)
    }

    pub fn update_assigned_at(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.assigned_at = value.try_timestamp().unwrap_or(self.assigned_at.clone());
        self.root.set(self.entity_key(), "assigned_at", value);
        self
    }

    pub fn changed_assigned_at(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "assigned_at")
    }

    pub fn eval_assigned_at(&self) -> teaql_core::eval::EvalResult<chrono::DateTime<chrono::Utc>> {
        if !self.is_loaded("assigned_at") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "assigned_at".to_string(), attempted_path: "assigned_at".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.assigned_at())
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
    pub fn user_id(&self) -> u64 {
        self.changed_user_id().and_then(|value| value.try_u64()).unwrap_or(self.user_id)
    }

    pub fn update_user_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.user_id = value.try_u64().unwrap_or(self.user_id.clone());
        self.root.set(self.entity_key(), "user_id", value);
        self
    }

    pub fn changed_user_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "user_id")
    }

    pub fn eval_user_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("user_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "user_id".to_string(), attempted_path: "user_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.user_id())
                }}

    pub fn role_id(&self) -> u64 {
        self.changed_role_id().and_then(|value| value.try_u64()).unwrap_or(self.role_id)
    }

    pub fn update_role_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.role_id = value.try_u64().unwrap_or(self.role_id.clone());
        self.root.set(self.entity_key(), "role_id", value);
        self
    }

    pub fn changed_role_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "role_id")
    }

    pub fn eval_role_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("role_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "role_id".to_string(), attempted_path: "role_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.role_id())
                }}
    pub fn user(&self) -> Option<&crate::User> {
        self.user.as_ref()
    }

    pub fn eval_user(&self) -> teaql_core::eval::EvalResult<&crate::User> {
        if !self.is_loaded("user") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "user".to_string(), attempted_path: "user".to_string() }
        } else {
            match &self.user {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn role(&self) -> Option<&crate::Role> {
        self.role.as_ref()
    }

    pub fn eval_role(&self) -> teaql_core::eval::EvalResult<&crate::Role> {
        if !self.is_loaded("role") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "role".to_string(), attempted_path: "role".to_string() }
        } else {
            match &self.role {
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

    pub(crate) async fn save<'a, C>(
        &self,
        ctx: &'a C,
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::UserRoleRepository<'a>>>
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
            .user_role_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("UserRole"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

