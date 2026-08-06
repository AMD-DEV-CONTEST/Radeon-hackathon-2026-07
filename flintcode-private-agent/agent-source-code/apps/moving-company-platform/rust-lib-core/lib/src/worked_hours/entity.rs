
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/worked_hours
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "WorkedHours", table = "worked_hours_data", data_service = "sqlite")]
pub struct WorkedHours {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:68
    hours_count: rust_decimal::Decimal,

// @source moving-company.xml:68
    work_date: chrono::NaiveDate,

// @source moving-company.xml:68
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:68
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:68
#[teaql(column = "payroll_calculation")]
    payroll_calculation_id: u64,

// @source moving-company.xml:68
#[teaql(column = "employee_record")]
    employee_record_id: u64,
// @source moving-company.xml:68
#[teaql(relation(target = "PayrollCalculation", local_key = "payroll_calculation_id", foreign_key = "id"))]
    payroll_calculation: Option<crate::PayrollCalculation>,

// @source moving-company.xml:68
#[teaql(relation(target = "EmployeeRecord", local_key = "employee_record_id", foreign_key = "id"))]
    employee_record: Option<crate::EmployeeRecord>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl WorkedHours {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            hours_count: rust_decimal::Decimal::ZERO,
            work_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            payroll_calculation_id: 0_u64,
            employee_record_id: 0_u64,
            payroll_calculation: None,
            employee_record: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("WorkedHours", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.payroll_calculation {
            entity.attach_root_recursive(root.clone());
        }
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

    pub fn hours_count(&self) -> rust_decimal::Decimal {
        self.changed_hours_count().and_then(|value| value.try_decimal()).unwrap_or(self.hours_count)
    }

    pub fn update_hours_count(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.hours_count = value.try_decimal().unwrap_or(self.hours_count.clone());
        self.root.set(self.entity_key(), "hours_count", value);
        self
    }

    pub fn changed_hours_count(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "hours_count")
    }

    pub fn eval_hours_count(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("hours_count") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "hours_count".to_string(), attempted_path: "hours_count".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.hours_count())
                }}

    pub fn work_date(&self) -> chrono::NaiveDate {
        self.changed_work_date().and_then(|value| value.try_date()).unwrap_or(self.work_date)
    }

    pub fn update_work_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.work_date = value.try_date().unwrap_or(self.work_date.clone());
        self.root.set(self.entity_key(), "work_date", value);
        self
    }

    pub fn changed_work_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "work_date")
    }

    pub fn eval_work_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("work_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "work_date".to_string(), attempted_path: "work_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.work_date())
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
    pub fn payroll_calculation_id(&self) -> u64 {
        self.changed_payroll_calculation_id().and_then(|value| value.try_u64()).unwrap_or(self.payroll_calculation_id)
    }

    pub fn update_payroll_calculation_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.payroll_calculation_id = value.try_u64().unwrap_or(self.payroll_calculation_id.clone());
        self.root.set(self.entity_key(), "payroll_calculation_id", value);
        self
    }

    pub fn changed_payroll_calculation_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "payroll_calculation_id")
    }

    pub fn eval_payroll_calculation_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("payroll_calculation_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "payroll_calculation_id".to_string(), attempted_path: "payroll_calculation_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.payroll_calculation_id())
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
    pub fn payroll_calculation(&self) -> Option<&crate::PayrollCalculation> {
        self.payroll_calculation.as_ref()
    }

    pub fn eval_payroll_calculation(&self) -> teaql_core::eval::EvalResult<&crate::PayrollCalculation> {
        if !self.is_loaded("payroll_calculation") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "payroll_calculation".to_string(), attempted_path: "payroll_calculation".to_string() }
        } else {
            match &self.payroll_calculation {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn employee_record(&self) -> Option<&crate::EmployeeRecord> {
        self.employee_record.as_ref()
    }

    pub fn eval_employee_record(&self) -> teaql_core::eval::EvalResult<&crate::EmployeeRecord> {
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

