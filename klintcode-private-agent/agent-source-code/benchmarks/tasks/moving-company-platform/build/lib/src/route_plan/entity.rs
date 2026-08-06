
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/route_plan
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "RoutePlan", table = "route_plan_data", data_service = "sqlite")]
pub struct RoutePlan {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:260
    estimated_distance: rust_decimal::Decimal,

// @source moving-company.xml:260
    estimated_duration: i64,

// @source moving-company.xml:260
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:260
#[teaql(column = "move_order")]
    move_order_id: u64,
// @source moving-company.xml:260
#[teaql(relation(target = "MoveOrder", local_key = "move_order_id", foreign_key = "id"))]
    move_order: Option<crate::MoveOrder>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl RoutePlan {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            estimated_distance: rust_decimal::Decimal::ZERO,
            estimated_duration: 0_i64,
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            move_order_id: 0_u64,
            move_order: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("RoutePlan", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.move_order {
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

    pub fn estimated_distance(&self) -> rust_decimal::Decimal {
        self.changed_estimated_distance().and_then(|value| value.try_decimal()).unwrap_or(self.estimated_distance)
    }

    pub fn update_estimated_distance(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.estimated_distance = value.try_decimal().unwrap_or(self.estimated_distance.clone());
        self.root.set(self.entity_key(), "estimated_distance", value);
        self
    }

    pub fn changed_estimated_distance(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "estimated_distance")
    }

    pub fn eval_estimated_distance(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("estimated_distance") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "estimated_distance".to_string(), attempted_path: "estimated_distance".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.estimated_distance())
                }}

    pub fn estimated_duration(&self) -> i64 {
        self.changed_estimated_duration().and_then(|value| value.try_i64()).map(|value| value as i64).unwrap_or(self.estimated_duration)
    }

    pub fn update_estimated_duration(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.estimated_duration = value.try_i64().map(|value| value as i64).unwrap_or(self.estimated_duration.clone());
        self.root.set(self.entity_key(), "estimated_duration", value);
        self
    }

    pub fn changed_estimated_duration(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "estimated_duration")
    }

    pub fn eval_estimated_duration(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("estimated_duration") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "estimated_duration".to_string(), attempted_path: "estimated_duration".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.estimated_duration())
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
    pub fn move_order_id(&self) -> u64 {
        self.changed_move_order_id().and_then(|value| value.try_u64()).unwrap_or(self.move_order_id)
    }

    pub fn update_move_order_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.move_order_id = value.try_u64().unwrap_or(self.move_order_id.clone());
        self.root.set(self.entity_key(), "move_order_id", value);
        self
    }

    pub fn changed_move_order_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "move_order_id")
    }

    pub fn eval_move_order_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("move_order_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_order_id".to_string(), attempted_path: "move_order_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.move_order_id())
                }}
    pub fn move_order(&self) -> Option<&crate::MoveOrder> {
        self.move_order.as_ref()
    }

    pub fn eval_move_order(&self) -> teaql_core::eval::EvalResult<&crate::MoveOrder> {
        if !self.is_loaded("move_order") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_order".to_string(), attempted_path: "move_order".to_string() }
        } else {
            match &self.move_order {
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

