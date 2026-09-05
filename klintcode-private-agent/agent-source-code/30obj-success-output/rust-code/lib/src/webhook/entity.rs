// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/webhook
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "Webhook", table = "webhook_data", data_service = "sqlite", audit_mask_fields = "secret_key")]
pub struct Webhook {
#[teaql(id)]
    id: u64,

// @source platform_modules.xml:111
    url: String,

// @source platform_modules.xml:111
    event_type: String,

// @source platform_modules.xml:111
    secret_key: String,

// @source platform_modules.xml:111
    active: bool,

// @source platform_modules.xml:111
    create_time: chrono::DateTime<chrono::Utc>,

// @source platform_modules.xml:111
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl Webhook {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            url: String::new(),
            event_type: String::new(),
            secret_key: String::new(),
            active: false,
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("Webhook", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
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

    pub fn url(&self) -> String {
        self.changed_url().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.url.clone())
    }

    pub fn update_url(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.url = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.url.clone());
        self.root.set(self.entity_key(), "url", value);
        self
    }

    pub fn changed_url(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "url")
    }

    pub fn eval_url(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("url") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "url".to_string(), attempted_path: "url".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.url())
                }}

    pub fn event_type(&self) -> String {
        self.changed_event_type().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.event_type.clone())
    }

    pub fn update_event_type(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.event_type = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.event_type.clone());
        self.root.set(self.entity_key(), "event_type", value);
        self
    }

    pub fn changed_event_type(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "event_type")
    }

    pub fn eval_event_type(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("event_type") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "event_type".to_string(), attempted_path: "event_type".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.event_type())
                }}

    pub fn secret_key(&self) -> String {
        self.changed_secret_key().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.secret_key.clone())
    }

    pub fn update_secret_key(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.secret_key = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.secret_key.clone());
        self.root.set(self.entity_key(), "secret_key", value);
        self
    }

    pub fn changed_secret_key(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "secret_key")
    }

    pub fn eval_secret_key(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("secret_key") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "secret_key".to_string(), attempted_path: "secret_key".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.secret_key())
                }}

    pub fn active(&self) -> bool {
        self.changed_active().and_then(|value| value.try_bool()).unwrap_or(self.active)
    }

    pub fn update_active(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.active = value.try_bool().unwrap_or(self.active.clone());
        self.root.set(self.entity_key(), "active", value);
        self
    }

    pub fn changed_active(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "active")
    }

    pub fn eval_active(&self) -> teaql_core::eval::EvalResult<bool> {
        if !self.is_loaded("active") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "active".to_string(), attempted_path: "active".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.active())
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::WebhookRepository<'a>>>
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
            .webhook_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("Webhook"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

