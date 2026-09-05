// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/route
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "Route", table = "route_data", data_service = "sqlite")]
pub struct Route {
#[teaql(id)]
    id: u64,

// @source operations.xml:42
    route_name: String,

// @source operations.xml:42
    distance_km: rust_decimal::Decimal,

// @source operations.xml:42
    estimated_time_minutes: i64,

// @source operations.xml:42
    create_time: chrono::DateTime<chrono::Utc>,

// @source operations.xml:42
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source operations.xml:42
#[teaql(column = "origin")]
    origin_id: u64,

// @source operations.xml:42
#[teaql(column = "destination")]
    destination_id: u64,
// @source operations.xml:42
#[teaql(relation(target = "Address", local_key = "origin_id", foreign_key = "id"))]
    origin: Option<crate::Address>,

// @source operations.xml:42
#[teaql(relation(target = "Address", local_key = "destination_id", foreign_key = "id"))]
    destination: Option<crate::Address>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl Route {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            route_name: String::new(),
            distance_km: rust_decimal::Decimal::ZERO,
            estimated_time_minutes: 0_i64,
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            origin_id: 0_u64,
            destination_id: 0_u64,
            origin: None,
            destination: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("Route", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.origin {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.destination {
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

    pub fn route_name(&self) -> String {
        self.changed_route_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.route_name.clone())
    }

    pub fn update_route_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.route_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.route_name.clone());
        self.root.set(self.entity_key(), "route_name", value);
        self
    }

    pub fn changed_route_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "route_name")
    }

    pub fn eval_route_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("route_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "route_name".to_string(), attempted_path: "route_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.route_name())
                }}

    pub fn distance_km(&self) -> rust_decimal::Decimal {
        self.changed_distance_km().and_then(|value| value.try_decimal()).unwrap_or(self.distance_km)
    }

    pub fn update_distance_km(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.distance_km = value.try_decimal().unwrap_or(self.distance_km.clone());
        self.root.set(self.entity_key(), "distance_km", value);
        self
    }

    pub fn changed_distance_km(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "distance_km")
    }

    pub fn eval_distance_km(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("distance_km") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "distance_km".to_string(), attempted_path: "distance_km".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.distance_km())
                }}

    pub fn estimated_time_minutes(&self) -> i64 {
        self.changed_estimated_time_minutes().and_then(|value| value.try_i64()).map(|value| value as i64).unwrap_or(self.estimated_time_minutes)
    }

    pub fn update_estimated_time_minutes(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.estimated_time_minutes = value.try_i64().map(|value| value as i64).unwrap_or(self.estimated_time_minutes.clone());
        self.root.set(self.entity_key(), "estimated_time_minutes", value);
        self
    }

    pub fn changed_estimated_time_minutes(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "estimated_time_minutes")
    }

    pub fn eval_estimated_time_minutes(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("estimated_time_minutes") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "estimated_time_minutes".to_string(), attempted_path: "estimated_time_minutes".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.estimated_time_minutes())
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
    pub fn origin_id(&self) -> u64 {
        self.changed_origin_id().and_then(|value| value.try_u64()).unwrap_or(self.origin_id)
    }

    pub fn update_origin_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.origin_id = value.try_u64().unwrap_or(self.origin_id.clone());
        self.root.set(self.entity_key(), "origin_id", value);
        self
    }

    pub fn changed_origin_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "origin_id")
    }

    pub fn eval_origin_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("origin_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "origin_id".to_string(), attempted_path: "origin_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.origin_id())
                }}

    pub fn destination_id(&self) -> u64 {
        self.changed_destination_id().and_then(|value| value.try_u64()).unwrap_or(self.destination_id)
    }

    pub fn update_destination_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.destination_id = value.try_u64().unwrap_or(self.destination_id.clone());
        self.root.set(self.entity_key(), "destination_id", value);
        self
    }

    pub fn changed_destination_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "destination_id")
    }

    pub fn eval_destination_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("destination_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "destination_id".to_string(), attempted_path: "destination_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.destination_id())
                }}
    pub fn origin(&self) -> Option<&crate::Address> {
        self.origin.as_ref()
    }

    pub fn eval_origin(&self) -> teaql_core::eval::EvalResult<&crate::Address> {
        if !self.is_loaded("origin") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "origin".to_string(), attempted_path: "origin".to_string() }
        } else {
            match &self.origin {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn destination(&self) -> Option<&crate::Address> {
        self.destination.as_ref()
    }

    pub fn eval_destination(&self) -> teaql_core::eval::EvalResult<&crate::Address> {
        if !self.is_loaded("destination") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "destination".to_string(), attempted_path: "destination".to_string() }
        } else {
            match &self.destination {
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::RouteRepository<'a>>>
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
            .route_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("Route"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

