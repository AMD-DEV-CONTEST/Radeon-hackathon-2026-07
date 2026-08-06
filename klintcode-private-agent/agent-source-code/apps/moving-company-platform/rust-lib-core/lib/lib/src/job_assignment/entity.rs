
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/job_assignment
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
#[teaql(entity = "JobAssignment", table = "job_assignment_data", data_service = "sqlite")]
pub struct JobAssignment {
#[teaql(id)]
    id: u64,

// @source employees.xml:43
    assignment_role: String,

// @source employees.xml:43
    assignment_date: chrono::NaiveDate,

// @source employees.xml:43
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source employees.xml:43
#[teaql(column = "move_order")]
    move_order_id: u64,

// @source employees.xml:43
#[teaql(column = "employee_record")]
    employee_record_id: u64,
// @source employees.xml:43
#[teaql(relation(target = "MoveOrder", local_key = "move_order_id", foreign_key = "id"))]
    move_order: Option<crate::MoveOrder>,

// @source employees.xml:43
#[teaql(relation(target = "EmployeeRegistry", local_key = "employee_record_id", foreign_key = "id"))]
    employee_record: Option<crate::EmployeeRegistry>,
#[teaql(relation(target = "WorkedHours", local_key = "id", foreign_key = "job_assignment_id", many))]
    worked_hours_list: SmartList<crate::WorkedHours>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl JobAssignment {
    pub const ENTITY_NAME: &'static str = "Job Assignment";

    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            assignment_role: String::new(),
            assignment_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            move_order_id: 0_u64,
            employee_record_id: 0_u64,
            move_order: None,
            employee_record: None,
            worked_hours_list: Default::default(),
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
        if let Some(entity) = &mut self.move_order {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.employee_record {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.worked_hours_list {
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

    pub fn assignment_role(&self) -> String {
        self.changed_assignment_role().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.assignment_role.clone())
    }

    pub fn update_assignment_role(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.assignment_role = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.assignment_role.clone());
        self.root.set(self.entity_key(), "assignment_role", value);
        self
    }

    pub fn changed_assignment_role(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "assignment_role")
    }

    pub fn eval_assignment_role(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("assignment_role") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "assignment_role".to_string(), attempted_path: "assignment_role".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.assignment_role())
                }}

    pub fn assignment_date(&self) -> chrono::NaiveDate {
        self.changed_assignment_date().and_then(|value| value.try_date()).unwrap_or(self.assignment_date)
    }

    pub fn update_assignment_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.assignment_date = value.try_date().unwrap_or(self.assignment_date.clone());
        self.root.set(self.entity_key(), "assignment_date", value);
        self
    }

    pub fn changed_assignment_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "assignment_date")
    }

    pub fn eval_assignment_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("assignment_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "assignment_date".to_string(), attempted_path: "assignment_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.assignment_date())
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
    pub fn worked_hours_list(&self) -> &SmartList<crate::WorkedHours> {
        &self.worked_hours_list
    }

    pub fn worked_hours_list_mut(&mut self) -> &mut SmartList<crate::WorkedHours> {
        &mut self.worked_hours_list
    }

    pub fn eval_worked_hours_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::WorkedHours>> {
        if !self.is_loaded("worked_hours_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "worked_hours_list".to_string(), attempted_path: "worked_hours_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.worked_hours_list)
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

