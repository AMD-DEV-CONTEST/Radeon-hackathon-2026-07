
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/shift_schedule
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "ShiftSchedule", table = "shift_schedule_data", data_service = "sqlite")]
pub struct ShiftSchedule {
#[teaql(id)]
    id: u64,

// @source employees.xml:73
    shift_date: chrono::NaiveDate,

// @source employees.xml:73
    start_time: String,

// @source employees.xml:73
    end_time: String,

// @source employees.xml:73
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source employees.xml:73
#[teaql(column = "employee_record")]
    employee_record_id: u64,
// @source employees.xml:73
#[teaql(relation(target = "EmployeeRegistry", local_key = "employee_record_id", foreign_key = "id"))]
    employee_record: Option<crate::EmployeeRegistry>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl ShiftSchedule {
    pub const ENTITY_NAME: &'static str = "Shift Schedule";

    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            shift_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            start_time: String::new(),
            end_time: String::new(),
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            employee_record_id: 0_u64,
            employee_record: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("ShiftSchedule", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.employee_record {
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

    pub fn shift_date(&self) -> chrono::NaiveDate {
        self.changed_shift_date().and_then(|value| value.try_date()).unwrap_or(self.shift_date)
    }

    pub fn update_shift_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.shift_date = value.try_date().unwrap_or(self.shift_date.clone());
        self.root.set(self.entity_key(), "shift_date", value);
        self
    }

    pub fn changed_shift_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "shift_date")
    }

    pub fn eval_shift_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("shift_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "shift_date".to_string(), attempted_path: "shift_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.shift_date())
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
    pub fn employee_record_id(&self) -> u64 {
        self.changed_employee_record_id().and_then(|value| value.try_u64()).unwrap_or(self.employee_record_id)
    }

    pub fn update_employee_record_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.employee_record_id = value.try_u64().unwrap_or(self.employee_record_id.clone());
        self.root.set(self.entity_key(), "employee_record_id", value);
        self
    }

    pub fn changed_employee_record_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "employee_record_id")
    }

    pub fn eval_employee_record_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("employee_record_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "employee_record_id".to_string(), attempted_path: "employee_record_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.employee_record_id())
                }}
    pub fn employee_record(&self) -> Option<&crate::EmployeeRegistry> {
        self.employee_record.as_ref()
    }

    pub fn eval_employee_record(&self) -> teaql_core::eval::EvalResult<&crate::EmployeeRegistry> {
        if !self.is_loaded("employee_record") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "employee_record".to_string(), attempted_path: "employee_record".to_string() }
        } else {
            match &self.employee_record {
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

