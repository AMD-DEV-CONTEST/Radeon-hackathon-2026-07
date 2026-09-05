// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/job_assignment
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "JobAssignment", table = "job_assignment_data", data_service = "sqlite")]
pub struct JobAssignment {
#[teaql(id)]
    id: u64,

// @source employees.xml:35
    assignment_id: String,

// @source employees.xml:35
    start_time: String,

// @source employees.xml:35
    end_time: String,

// @source employees.xml:35
    role_on_job: String,

// @source employees.xml:35
    status: String,

// @source employees.xml:35
    create_time: chrono::DateTime<chrono::Utc>,

// @source employees.xml:35
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source employees.xml:35
#[teaql(column = "staff")]
    staff_id: u64,

// @source employees.xml:35
#[teaql(column = "moving_event")]
    moving_event_id: u64,
// @source employees.xml:35
#[teaql(relation(target = "Staff", local_key = "staff_id", foreign_key = "id"))]
    staff: Option<crate::Staff>,

// @source employees.xml:35
#[teaql(relation(target = "MovingEvent", local_key = "moving_event_id", foreign_key = "id"))]
    moving_event: Option<crate::MovingEvent>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl JobAssignment {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            assignment_id: String::new(),
            start_time: String::new(),
            end_time: String::new(),
            role_on_job: String::new(),
            status: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            staff_id: 0_u64,
            moving_event_id: 0_u64,
            staff: None,
            moving_event: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("JobAssignment", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.staff {
            entity.attach_root_recursive(root.clone());
        }
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

    pub fn assignment_id(&self) -> String {
        self.changed_assignment_id().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.assignment_id.clone())
    }

    pub fn update_assignment_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.assignment_id = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.assignment_id.clone());
        self.root.set(self.entity_key(), "assignment_id", value);
        self
    }

    pub fn changed_assignment_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "assignment_id")
    }

    pub fn eval_assignment_id(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("assignment_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "assignment_id".to_string(), attempted_path: "assignment_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.assignment_id())
                }}

    pub fn start_time(&self) -> String {
        self.changed_start_time().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.start_time.clone())
    }

    pub fn update_start_time(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.start_time = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.start_time.clone());
        self.root.set(self.entity_key(), "start_time", value);
        self
    }

    pub fn changed_start_time(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "start_time")
    }

    pub fn eval_start_time(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("start_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "start_time".to_string(), attempted_path: "start_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.start_time())
                }}

    pub fn end_time(&self) -> String {
        self.changed_end_time().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.end_time.clone())
    }

    pub fn update_end_time(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.end_time = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.end_time.clone());
        self.root.set(self.entity_key(), "end_time", value);
        self
    }

    pub fn changed_end_time(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "end_time")
    }

    pub fn eval_end_time(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("end_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "end_time".to_string(), attempted_path: "end_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.end_time())
                }}

    pub fn role_on_job(&self) -> String {
        self.changed_role_on_job().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.role_on_job.clone())
    }

    pub fn update_role_on_job(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.role_on_job = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.role_on_job.clone());
        self.root.set(self.entity_key(), "role_on_job", value);
        self
    }

    pub fn changed_role_on_job(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "role_on_job")
    }

    pub fn eval_role_on_job(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("role_on_job") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "role_on_job".to_string(), attempted_path: "role_on_job".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.role_on_job())
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
    pub fn staff_id(&self) -> u64 {
        self.changed_staff_id().and_then(|value| value.try_u64()).unwrap_or(self.staff_id)
    }

    pub fn update_staff_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.staff_id = value.try_u64().unwrap_or(self.staff_id.clone());
        self.root.set(self.entity_key(), "staff_id", value);
        self
    }

    pub fn changed_staff_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "staff_id")
    }

    pub fn eval_staff_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("staff_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "staff_id".to_string(), attempted_path: "staff_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.staff_id())
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
    pub fn staff(&self) -> Option<&crate::Staff> {
        self.staff.as_ref()
    }

    pub fn eval_staff(&self) -> teaql_core::eval::EvalResult<&crate::Staff> {
        if !self.is_loaded("staff") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "staff".to_string(), attempted_path: "staff".to_string() }
        } else {
            match &self.staff {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::JobAssignmentRepository<'a>>>
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
            .job_assignment_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("JobAssignment"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

