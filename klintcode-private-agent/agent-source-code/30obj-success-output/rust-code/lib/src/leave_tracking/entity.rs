// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/leave_tracking
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "LeaveTracking", table = "leave_tracking_data", data_service = "sqlite")]
pub struct LeaveTracking {
#[teaql(id)]
    id: u64,

// @source employees.xml:85
    leave_type: String,

// @source employees.xml:85
    start_date: chrono::NaiveDate,

// @source employees.xml:85
    end_date: chrono::NaiveDate,

// @source employees.xml:85
    days_requested: rust_decimal::Decimal,

// @source employees.xml:85
    status: String,

// @source employees.xml:85
    create_time: chrono::DateTime<chrono::Utc>,

// @source employees.xml:85
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source employees.xml:85
#[teaql(column = "staff")]
    staff_id: u64,
// @source employees.xml:85
#[teaql(relation(target = "Staff", local_key = "staff_id", foreign_key = "id"))]
    staff: Option<crate::Staff>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl LeaveTracking {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            leave_type: String::new(),
            start_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            end_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            days_requested: rust_decimal::Decimal::ZERO,
            status: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            staff_id: 0_u64,
            staff: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("LeaveTracking", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.staff {
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

    pub fn leave_type(&self) -> String {
        self.changed_leave_type().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.leave_type.clone())
    }

    pub fn update_leave_type(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.leave_type = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.leave_type.clone());
        self.root.set(self.entity_key(), "leave_type", value);
        self
    }

    pub fn changed_leave_type(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "leave_type")
    }

    pub fn eval_leave_type(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("leave_type") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "leave_type".to_string(), attempted_path: "leave_type".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.leave_type())
                }}

    pub fn start_date(&self) -> chrono::NaiveDate {
        self.changed_start_date().and_then(|value| value.try_date()).unwrap_or(self.start_date)
    }

    pub fn update_start_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.start_date = value.try_date().unwrap_or(self.start_date.clone());
        self.root.set(self.entity_key(), "start_date", value);
        self
    }

    pub fn changed_start_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "start_date")
    }

    pub fn eval_start_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("start_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "start_date".to_string(), attempted_path: "start_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.start_date())
                }}

    pub fn end_date(&self) -> chrono::NaiveDate {
        self.changed_end_date().and_then(|value| value.try_date()).unwrap_or(self.end_date)
    }

    pub fn update_end_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.end_date = value.try_date().unwrap_or(self.end_date.clone());
        self.root.set(self.entity_key(), "end_date", value);
        self
    }

    pub fn changed_end_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "end_date")
    }

    pub fn eval_end_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("end_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "end_date".to_string(), attempted_path: "end_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.end_date())
                }}

    pub fn days_requested(&self) -> rust_decimal::Decimal {
        self.changed_days_requested().and_then(|value| value.try_decimal()).unwrap_or(self.days_requested)
    }

    pub fn update_days_requested(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.days_requested = value.try_decimal().unwrap_or(self.days_requested.clone());
        self.root.set(self.entity_key(), "days_requested", value);
        self
    }

    pub fn changed_days_requested(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "days_requested")
    }

    pub fn eval_days_requested(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("days_requested") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "days_requested".to_string(), attempted_path: "days_requested".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.days_requested())
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::LeaveTrackingRepository<'a>>>
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
            .leave_tracking_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("LeaveTracking"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

