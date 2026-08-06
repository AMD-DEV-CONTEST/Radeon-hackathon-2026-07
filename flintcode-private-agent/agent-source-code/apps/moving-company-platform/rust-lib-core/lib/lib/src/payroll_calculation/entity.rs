
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/payroll_calculation
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "PayrollCalculation", table = "payroll_calculation_data", data_service = "sqlite")]
pub struct PayrollCalculation {
#[teaql(id)]
    id: u64,

// @source employees.xml:63
    pay_period: String,

// @source employees.xml:63
    base_salary: rust_decimal::Decimal,

// @source employees.xml:63
    overtime_hours: rust_decimal::Decimal,

// @source employees.xml:63
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source employees.xml:63
#[teaql(column = "employee_record")]
    employee_record_id: u64,
// @source employees.xml:63
#[teaql(relation(target = "EmployeeRegistry", local_key = "employee_record_id", foreign_key = "id"))]
    employee_record: Option<crate::EmployeeRegistry>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl PayrollCalculation {
    pub const ENTITY_NAME: &'static str = "Payroll Calculation";

    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            pay_period: String::new(),
            base_salary: rust_decimal::Decimal::ZERO,
            overtime_hours: rust_decimal::Decimal::ZERO,
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
        teaql_runtime::EntityKey::new("PayrollCalculation", self.id)
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

    pub fn pay_period(&self) -> String {
        self.changed_pay_period().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.pay_period.clone())
    }

    pub fn update_pay_period(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.pay_period = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.pay_period.clone());
        self.root.set(self.entity_key(), "pay_period", value);
        self
    }

    pub fn changed_pay_period(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "pay_period")
    }

    pub fn eval_pay_period(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("pay_period") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "pay_period".to_string(), attempted_path: "pay_period".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.pay_period())
                }}

    pub fn base_salary(&self) -> rust_decimal::Decimal {
        self.changed_base_salary().and_then(|value| value.try_decimal()).unwrap_or(self.base_salary)
    }

    pub fn update_base_salary(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.base_salary = value.try_decimal().unwrap_or(self.base_salary.clone());
        self.root.set(self.entity_key(), "base_salary", value);
        self
    }

    pub fn changed_base_salary(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "base_salary")
    }

    pub fn eval_base_salary(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("base_salary") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "base_salary".to_string(), attempted_path: "base_salary".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.base_salary())
                }}

    pub fn overtime_hours(&self) -> rust_decimal::Decimal {
        self.changed_overtime_hours().and_then(|value| value.try_decimal()).unwrap_or(self.overtime_hours)
    }

    pub fn update_overtime_hours(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.overtime_hours = value.try_decimal().unwrap_or(self.overtime_hours.clone());
        self.root.set(self.entity_key(), "overtime_hours", value);
        self
    }

    pub fn changed_overtime_hours(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "overtime_hours")
    }

    pub fn eval_overtime_hours(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("overtime_hours") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "overtime_hours".to_string(), attempted_path: "overtime_hours".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.overtime_hours())
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

