// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/moving_event
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
#[teaql(entity = "MovingEvent", table = "moving_event_data", data_service = "sqlite")]
pub struct MovingEvent {
#[teaql(id)]
    id: u64,

// @source operations.xml:31
    event_name: String,

// @source operations.xml:31
    scheduled_date: chrono::NaiveDate,

// @source operations.xml:31
    status: String,

// @source operations.xml:31
    customer: String,

// @source operations.xml:31
    create_time: chrono::DateTime<chrono::Utc>,

// @source operations.xml:31
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source operations.xml:31
#[teaql(column = "origin_address")]
    origin_address_id: u64,

// @source operations.xml:31
#[teaql(column = "destination_address")]
    destination_address_id: u64,
// @source operations.xml:31
#[teaql(relation(target = "Address", local_key = "origin_address_id", foreign_key = "id"))]
    origin_address: Option<crate::Address>,

// @source operations.xml:31
#[teaql(relation(target = "Address", local_key = "destination_address_id", foreign_key = "id"))]
    destination_address: Option<crate::Address>,
#[teaql(relation(target = "TimeSlot", local_key = "id", foreign_key = "moving_event_id", many))]
    time_slot_list: SmartList<crate::TimeSlot>,
#[teaql(relation(target = "FulfillmentEvent", local_key = "id", foreign_key = "moving_event_id", many))]
    fulfillment_event_list: SmartList<crate::FulfillmentEvent>,
#[teaql(relation(target = "JobAssignment", local_key = "id", foreign_key = "moving_event_id", many))]
    job_assignment_list: SmartList<crate::JobAssignment>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl MovingEvent {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            event_name: String::new(),
            scheduled_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            status: String::new(),
            customer: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            origin_address_id: 0_u64,
            destination_address_id: 0_u64,
            origin_address: None,
            destination_address: None,
            time_slot_list: Default::default(),
            fulfillment_event_list: Default::default(),
            job_assignment_list: Default::default(),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("MovingEvent", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.origin_address {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.destination_address {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.time_slot_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.fulfillment_event_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.job_assignment_list {
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

    pub fn event_name(&self) -> String {
        self.changed_event_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.event_name.clone())
    }

    pub fn update_event_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.event_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.event_name.clone());
        self.root.set(self.entity_key(), "event_name", value);
        self
    }

    pub fn changed_event_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "event_name")
    }

    pub fn eval_event_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("event_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "event_name".to_string(), attempted_path: "event_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.event_name())
                }}

    pub fn scheduled_date(&self) -> chrono::NaiveDate {
        self.changed_scheduled_date().and_then(|value| value.try_date()).unwrap_or(self.scheduled_date)
    }

    pub fn update_scheduled_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.scheduled_date = value.try_date().unwrap_or(self.scheduled_date.clone());
        self.root.set(self.entity_key(), "scheduled_date", value);
        self
    }

    pub fn changed_scheduled_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "scheduled_date")
    }

    pub fn eval_scheduled_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("scheduled_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "scheduled_date".to_string(), attempted_path: "scheduled_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.scheduled_date())
                }}

    pub fn status(&self) -> String {
        self.changed_status().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.status.clone())
    }

    pub fn update_status(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.status = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.status.clone());
        self.root.set(self.entity_key(), "status", value);
        self
    }

    pub fn changed_status(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "status")
    }

    pub fn eval_status(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("status") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "status".to_string(), attempted_path: "status".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.status())
                }}

    pub fn customer(&self) -> String {
        self.changed_customer().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.customer.clone())
    }

    pub fn update_customer(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.customer = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.customer.clone());
        self.root.set(self.entity_key(), "customer", value);
        self
    }

    pub fn changed_customer(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "customer")
    }

    pub fn eval_customer(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("customer") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "customer".to_string(), attempted_path: "customer".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.customer())
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
    pub fn origin_address_id(&self) -> u64 {
        self.changed_origin_address_id().and_then(|value| value.try_u64()).unwrap_or(self.origin_address_id)
    }

    pub fn update_origin_address_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.origin_address_id = value.try_u64().unwrap_or(self.origin_address_id.clone());
        self.root.set(self.entity_key(), "origin_address_id", value);
        self
    }

    pub fn changed_origin_address_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "origin_address_id")
    }

    pub fn eval_origin_address_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("origin_address_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "origin_address_id".to_string(), attempted_path: "origin_address_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.origin_address_id())
                }}

    pub fn destination_address_id(&self) -> u64 {
        self.changed_destination_address_id().and_then(|value| value.try_u64()).unwrap_or(self.destination_address_id)
    }

    pub fn update_destination_address_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.destination_address_id = value.try_u64().unwrap_or(self.destination_address_id.clone());
        self.root.set(self.entity_key(), "destination_address_id", value);
        self
    }

    pub fn changed_destination_address_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "destination_address_id")
    }

    pub fn eval_destination_address_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("destination_address_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "destination_address_id".to_string(), attempted_path: "destination_address_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.destination_address_id())
                }}
    pub fn origin_address(&self) -> Option<&crate::Address> {
        self.origin_address.as_ref()
    }

    pub fn eval_origin_address(&self) -> teaql_core::eval::EvalResult<&crate::Address> {
        if !self.is_loaded("origin_address") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "origin_address".to_string(), attempted_path: "origin_address".to_string() }
        } else {
            match &self.origin_address {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn destination_address(&self) -> Option<&crate::Address> {
        self.destination_address.as_ref()
    }

    pub fn eval_destination_address(&self) -> teaql_core::eval::EvalResult<&crate::Address> {
        if !self.is_loaded("destination_address") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "destination_address".to_string(), attempted_path: "destination_address".to_string() }
        } else {
            match &self.destination_address {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }
    pub fn time_slot_list(&self) -> &SmartList<crate::TimeSlot> {
        &self.time_slot_list
    }

    pub fn time_slot_list_mut(&mut self) -> &mut SmartList<crate::TimeSlot> {
        &mut self.time_slot_list
    }

    pub fn eval_time_slot_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::TimeSlot>> {
        if !self.is_loaded("time_slot_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "time_slot_list".to_string(), attempted_path: "time_slot_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.time_slot_list)
        }
    }

    pub fn fulfillment_event_list(&self) -> &SmartList<crate::FulfillmentEvent> {
        &self.fulfillment_event_list
    }

    pub fn fulfillment_event_list_mut(&mut self) -> &mut SmartList<crate::FulfillmentEvent> {
        &mut self.fulfillment_event_list
    }

    pub fn eval_fulfillment_event_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::FulfillmentEvent>> {
        if !self.is_loaded("fulfillment_event_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "fulfillment_event_list".to_string(), attempted_path: "fulfillment_event_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.fulfillment_event_list)
        }
    }

    pub fn job_assignment_list(&self) -> &SmartList<crate::JobAssignment> {
        &self.job_assignment_list
    }

    pub fn job_assignment_list_mut(&mut self) -> &mut SmartList<crate::JobAssignment> {
        &mut self.job_assignment_list
    }

    pub fn eval_job_assignment_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::JobAssignment>> {
        if !self.is_loaded("job_assignment_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "job_assignment_list".to_string(), attempted_path: "job_assignment_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.job_assignment_list)
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::MovingEventRepository<'a>>>
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
            .moving_event_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("MovingEvent"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

