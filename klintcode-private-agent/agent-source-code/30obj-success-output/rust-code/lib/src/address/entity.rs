// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/address
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
#[teaql(entity = "Address", table = "address_data", data_service = "sqlite")]
pub struct Address {
#[teaql(id)]
    id: u64,

// @source operations.xml:19
    street: String,

// @source operations.xml:19
    city: String,

// @source operations.xml:19
    state: String,

// @source operations.xml:19
    postal_code: i64,

// @source operations.xml:19
    country: String,

// @source operations.xml:19
    create_time: chrono::DateTime<chrono::Utc>,

// @source operations.xml:19
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
#[teaql(relation(target = "MovingEvent", local_key = "id", foreign_key = "origin_address_id", many))]
    moving_event_list_as_origin_address: SmartList<crate::MovingEvent>,
#[teaql(relation(target = "MovingEvent", local_key = "id", foreign_key = "destination_address_id", many))]
    moving_event_list_as_destination_address: SmartList<crate::MovingEvent>,
#[teaql(relation(target = "Route", local_key = "id", foreign_key = "origin_id", many))]
    route_list_as_origin: SmartList<crate::Route>,
#[teaql(relation(target = "Route", local_key = "id", foreign_key = "destination_id", many))]
    route_list_as_destination: SmartList<crate::Route>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl Address {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            street: String::new(),
            city: String::new(),
            state: String::new(),
            postal_code: 0_i64,
            country: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            moving_event_list_as_origin_address: Default::default(),
            moving_event_list_as_destination_address: Default::default(),
            route_list_as_origin: Default::default(),
            route_list_as_destination: Default::default(),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("Address", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        for entity in &mut self.moving_event_list_as_origin_address {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.moving_event_list_as_destination_address {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.route_list_as_origin {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.route_list_as_destination {
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

    pub fn street(&self) -> String {
        self.changed_street().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.street.clone())
    }

    pub fn update_street(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.street = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.street.clone());
        self.root.set(self.entity_key(), "street", value);
        self
    }

    pub fn changed_street(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "street")
    }

    pub fn eval_street(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("street") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "street".to_string(), attempted_path: "street".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.street())
                }}

    pub fn city(&self) -> String {
        self.changed_city().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.city.clone())
    }

    pub fn update_city(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.city = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.city.clone());
        self.root.set(self.entity_key(), "city", value);
        self
    }

    pub fn changed_city(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "city")
    }

    pub fn eval_city(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("city") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "city".to_string(), attempted_path: "city".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.city())
                }}

    pub fn state(&self) -> String {
        self.changed_state().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.state.clone())
    }

    pub fn update_state(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.state = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.state.clone());
        self.root.set(self.entity_key(), "state", value);
        self
    }

    pub fn changed_state(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "state")
    }

    pub fn eval_state(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("state") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "state".to_string(), attempted_path: "state".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.state())
                }}

    pub fn postal_code(&self) -> i64 {
        self.changed_postal_code().and_then(|value| value.try_i64()).map(|value| value as i64).unwrap_or(self.postal_code)
    }

    pub fn update_postal_code(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.postal_code = value.try_i64().map(|value| value as i64).unwrap_or(self.postal_code.clone());
        self.root.set(self.entity_key(), "postal_code", value);
        self
    }

    pub fn changed_postal_code(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "postal_code")
    }

    pub fn eval_postal_code(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("postal_code") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "postal_code".to_string(), attempted_path: "postal_code".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.postal_code())
                }}

    pub fn country(&self) -> String {
        self.changed_country().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.country.clone())
    }

    pub fn update_country(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.country = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.country.clone());
        self.root.set(self.entity_key(), "country", value);
        self
    }

    pub fn changed_country(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "country")
    }

    pub fn eval_country(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("country") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "country".to_string(), attempted_path: "country".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.country())
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
    pub fn moving_event_list_as_origin_address(&self) -> &SmartList<crate::MovingEvent> {
        &self.moving_event_list_as_origin_address
    }

    pub fn moving_event_list_as_origin_address_mut(&mut self) -> &mut SmartList<crate::MovingEvent> {
        &mut self.moving_event_list_as_origin_address
    }

    pub fn eval_moving_event_list_as_origin_address(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::MovingEvent>> {
        if !self.is_loaded("moving_event_list_as_origin_address") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "moving_event_list_as_origin_address".to_string(), attempted_path: "moving_event_list_as_origin_address".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.moving_event_list_as_origin_address)
        }
    }

    pub fn moving_event_list_as_destination_address(&self) -> &SmartList<crate::MovingEvent> {
        &self.moving_event_list_as_destination_address
    }

    pub fn moving_event_list_as_destination_address_mut(&mut self) -> &mut SmartList<crate::MovingEvent> {
        &mut self.moving_event_list_as_destination_address
    }

    pub fn eval_moving_event_list_as_destination_address(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::MovingEvent>> {
        if !self.is_loaded("moving_event_list_as_destination_address") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "moving_event_list_as_destination_address".to_string(), attempted_path: "moving_event_list_as_destination_address".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.moving_event_list_as_destination_address)
        }
    }

    pub fn route_list_as_origin(&self) -> &SmartList<crate::Route> {
        &self.route_list_as_origin
    }

    pub fn route_list_as_origin_mut(&mut self) -> &mut SmartList<crate::Route> {
        &mut self.route_list_as_origin
    }

    pub fn eval_route_list_as_origin(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::Route>> {
        if !self.is_loaded("route_list_as_origin") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "route_list_as_origin".to_string(), attempted_path: "route_list_as_origin".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.route_list_as_origin)
        }
    }

    pub fn route_list_as_destination(&self) -> &SmartList<crate::Route> {
        &self.route_list_as_destination
    }

    pub fn route_list_as_destination_mut(&mut self) -> &mut SmartList<crate::Route> {
        &mut self.route_list_as_destination
    }

    pub fn eval_route_list_as_destination(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::Route>> {
        if !self.is_loaded("route_list_as_destination") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "route_list_as_destination".to_string(), attempted_path: "route_list_as_destination".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.route_list_as_destination)
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::AddressRepository<'a>>>
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
            .address_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("Address"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

