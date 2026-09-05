// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/fulfillment_event
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "FulfillmentEvent", table = "fulfillment_event_data", data_service = "sqlite")]
pub struct FulfillmentEvent {
#[teaql(id)]
    id: u64,

// @source operations.xml:62
    event_type: String,

// @source operations.xml:62
    event_time: String,

// @source operations.xml:62
    description: String,

// @source operations.xml:62
    create_time: chrono::DateTime<chrono::Utc>,

// @source operations.xml:62
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source operations.xml:62
#[teaql(column = "moving_event")]
    moving_event_id: u64,
// @source operations.xml:62
#[teaql(relation(target = "MovingEvent", local_key = "moving_event_id", foreign_key = "id"))]
    moving_event: Option<crate::MovingEvent>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl FulfillmentEvent {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            event_type: String::new(),
            event_time: String::new(),
            description: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            moving_event_id: 0_u64,
            moving_event: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("FulfillmentEvent", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.moving_event {
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

    pub fn event_time(&self) -> String {
        self.changed_event_time().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.event_time.clone())
    }

    pub fn update_event_time(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.event_time = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.event_time.clone());
        self.root.set(self.entity_key(), "event_time", value);
        self
    }

    pub fn changed_event_time(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "event_time")
    }

    pub fn eval_event_time(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("event_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "event_time".to_string(), attempted_path: "event_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.event_time())
                }}

    pub fn description(&self) -> String {
        self.changed_description().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.description.clone())
    }

    pub fn update_description(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.description = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.description.clone());
        self.root.set(self.entity_key(), "description", value);
        self
    }

    pub fn changed_description(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "description")
    }

    pub fn eval_description(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("description") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "description".to_string(), attempted_path: "description".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.description())
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
    pub fn moving_event_id(&self) -> u64 {
        self.changed_moving_event_id().and_then(|value| value.try_u64()).unwrap_or(self.moving_event_id)
    }

    pub fn update_moving_event_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.moving_event_id = value.try_u64().unwrap_or(self.moving_event_id.clone());
        self.root.set(self.entity_key(), "moving_event_id", value);
        self
    }

    pub fn changed_moving_event_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "moving_event_id")
    }

    pub fn eval_moving_event_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("moving_event_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "moving_event_id".to_string(), attempted_path: "moving_event_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.moving_event_id())
                }}
    pub fn moving_event(&self) -> Option<&crate::MovingEvent> {
        self.moving_event.as_ref()
    }

    pub fn eval_moving_event(&self) -> teaql_core::eval::EvalResult<&crate::MovingEvent> {
        if !self.is_loaded("moving_event") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "moving_event".to_string(), attempted_path: "moving_event".to_string() }
        } else {
            match &self.moving_event {
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::FulfillmentEventRepository<'a>>>
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
            .fulfillment_event_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("FulfillmentEvent"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

