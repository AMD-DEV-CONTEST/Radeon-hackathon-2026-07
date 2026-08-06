
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/customer_feedback
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "CustomerFeedback", table = "customer_feedback_data", data_service = "sqlite")]
pub struct CustomerFeedback {
#[teaql(id)]
    id: u64,

// @source customers.xml:49
    feedback_comment: String,

// @source customers.xml:49
    feedback_date: chrono::NaiveDate,

// @source customers.xml:49
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source customers.xml:49
#[teaql(column = "customer_profile")]
    customer_profile_id: u64,

// @source customers.xml:49
#[teaql(column = "move_order")]
    move_order_id: u64,
// @source customers.xml:49
#[teaql(relation(target = "CustomerProfile", local_key = "customer_profile_id", foreign_key = "id"))]
    customer_profile: Option<crate::CustomerProfile>,

// @source customers.xml:49
#[teaql(relation(target = "MoveOrder", local_key = "move_order_id", foreign_key = "id"))]
    move_order: Option<crate::MoveOrder>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl CustomerFeedback {
    pub const ENTITY_NAME: &'static str = "Customer Feedback";

    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            feedback_comment: String::new(),
            feedback_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            customer_profile_id: 0_u64,
            move_order_id: 0_u64,
            customer_profile: None,
            move_order: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("CustomerFeedback", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.customer_profile {
            entity.attach_root_recursive(root.clone());
        }
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

    pub fn feedback_comment(&self) -> String {
        self.changed_feedback_comment().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.feedback_comment.clone())
    }

    pub fn update_feedback_comment(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.feedback_comment = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.feedback_comment.clone());
        self.root.set(self.entity_key(), "feedback_comment", value);
        self
    }

    pub fn changed_feedback_comment(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "feedback_comment")
    }

    pub fn eval_feedback_comment(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("feedback_comment") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "feedback_comment".to_string(), attempted_path: "feedback_comment".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.feedback_comment())
                }}

    pub fn feedback_date(&self) -> chrono::NaiveDate {
        self.changed_feedback_date().and_then(|value| value.try_date()).unwrap_or(self.feedback_date)
    }

    pub fn update_feedback_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.feedback_date = value.try_date().unwrap_or(self.feedback_date.clone());
        self.root.set(self.entity_key(), "feedback_date", value);
        self
    }

    pub fn changed_feedback_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "feedback_date")
    }

    pub fn eval_feedback_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("feedback_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "feedback_date".to_string(), attempted_path: "feedback_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.feedback_date())
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
    pub fn customer_profile_id(&self) -> u64 {
        self.changed_customer_profile_id().and_then(|value| value.try_u64()).unwrap_or(self.customer_profile_id)
    }

    pub fn update_customer_profile_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.customer_profile_id = value.try_u64().unwrap_or(self.customer_profile_id.clone());
        self.root.set(self.entity_key(), "customer_profile_id", value);
        self
    }

    pub fn changed_customer_profile_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "customer_profile_id")
    }

    pub fn eval_customer_profile_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("customer_profile_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "customer_profile_id".to_string(), attempted_path: "customer_profile_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.customer_profile_id())
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
    pub fn customer_profile(&self) -> Option<&crate::CustomerProfile> {
        self.customer_profile.as_ref()
    }

    pub fn eval_customer_profile(&self) -> teaql_core::eval::EvalResult<&crate::CustomerProfile> {
        if !self.is_loaded("customer_profile") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "customer_profile".to_string(), attempted_path: "customer_profile".to_string() }
        } else {
            match &self.customer_profile {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

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

