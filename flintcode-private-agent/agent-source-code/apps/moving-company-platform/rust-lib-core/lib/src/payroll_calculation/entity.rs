
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/payroll_calculation
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
#[teaql(entity = "PayrollCalculation", table = "payroll_calculation_data", data_service = "sqlite")]
pub struct PayrollCalculation {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:61
    period_start: chrono::NaiveDate,

// @source moving-company.xml:61
    period_end: chrono::NaiveDate,

// @source moving-company.xml:61
    total_amount: rust_decimal::Decimal,

// @source moving-company.xml:61
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:61
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:61
#[teaql(column = "employee_record")]
    employee_record_id: u64,
// @source moving-company.xml:61
#[teaql(relation(target = "EmployeeRecord", local_key = "employee_record_id", foreign_key = "id"))]
    employee_record: Option<crate::EmployeeRecord>,
#[teaql(relation(target = "WorkedHours", local_key = "id", foreign_key = "payroll_calculation_id", many))]
    worked_hours_list: SmartList<crate::WorkedHours>,
#[teaql(relation(target = "BonusRecord", local_key = "id", foreign_key = "payroll_calculation_id", many))]
    bonus_record_list: SmartList<crate::BonusRecord>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl PayrollCalculation {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            period_start: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            period_end: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            total_amount: rust_decimal::Decimal::ZERO,
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            employee_record_id: 0_u64,
            employee_record: None,
            worked_hours_list: Default::default(),
            bonus_record_list: Default::default(),
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
        for entity in &mut self.worked_hours_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.bonus_record_list {
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

    pub fn period_start(&self) -> chrono::NaiveDate {
        self.changed_period_start().and_then(|value| value.try_date()).unwrap_or(self.period_start)
    }

    pub fn update_period_start(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.period_start = value.try_date().unwrap_or(self.period_start.clone());
        self.root.set(self.entity_key(), "period_start", value);
        self
    }

    pub fn changed_period_start(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "period_start")
    }

    pub fn eval_period_start(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("period_start") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "period_start".to_string(), attempted_path: "period_start".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.period_start())
                }}

    pub fn period_end(&self) -> chrono::NaiveDate {
        self.changed_period_end().and_then(|value| value.try_date()).unwrap_or(self.period_end)
    }

    pub fn update_period_end(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.period_end = value.try_date().unwrap_or(self.period_end.clone());
        self.root.set(self.entity_key(), "period_end", value);
        self
    }

    pub fn changed_period_end(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "period_end")
    }

    pub fn eval_period_end(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("period_end") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "period_end".to_string(), attempted_path: "period_end".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.period_end())
                }}

    pub fn total_amount(&self) -> rust_decimal::Decimal {
        self.changed_total_amount().and_then(|value| value.try_decimal()).unwrap_or(self.total_amount)
    }

    pub fn update_total_amount(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.total_amount = value.try_decimal().unwrap_or(self.total_amount.clone());
        self.root.set(self.entity_key(), "total_amount", value);
        self
    }

    pub fn changed_total_amount(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "total_amount")
    }

    pub fn eval_total_amount(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("total_amount") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "total_amount".to_string(), attempted_path: "total_amount".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.total_amount())
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

    pub fn bonus_record_list(&self) -> &SmartList<crate::BonusRecord> {
        &self.bonus_record_list
    }

    pub fn bonus_record_list_mut(&mut self) -> &mut SmartList<crate::BonusRecord> {
        &mut self.bonus_record_list
    }

    pub fn eval_bonus_record_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::BonusRecord>> {
        if !self.is_loaded("bonus_record_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "bonus_record_list".to_string(), attempted_path: "bonus_record_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.bonus_record_list)
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

