
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/employee_registry
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
#[teaql(entity = "EmployeeRegistry", table = "employee_registry_data", data_service = "sqlite", audit_mask_fields = "ssn_number")]
pub struct EmployeeRegistry {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:110
    employee_name: String,

// @source moving-company.xml:110
    job_title: String,

// @source moving-company.xml:110
    hire_date: chrono::NaiveDate,

// @source moving-company.xml:110
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:110
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:110
#[teaql(column = "company_profile")]
    company_profile_id: u64,
// @source moving-company.xml:110
#[teaql(relation(target = "CompanyProfile", local_key = "company_profile_id", foreign_key = "id"))]
    company_profile: Option<crate::CompanyProfile>,
    #[teaql(boxed_relations)]
    pub _relations: Box<EmployeeRegistryReverseRelations>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl EmployeeRegistry {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            employee_name: String::new(),
            job_title: String::new(),
            hire_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            company_profile_id: 0_u64,
            company_profile: None,
            _relations: Box::new(EmployeeRegistryReverseRelations::new()),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("EmployeeRegistry", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.company_profile {
            entity.attach_root_recursive(root.clone());
        }
        self._relations.attach_root_recursive(root.clone());
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

    pub fn employee_name(&self) -> String {
        self.changed_employee_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.employee_name.clone())
    }

    pub fn update_employee_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.employee_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.employee_name.clone());
        self.root.set(self.entity_key(), "employee_name", value);
        self
    }

    pub fn changed_employee_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "employee_name")
    }

    pub fn eval_employee_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("employee_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "employee_name".to_string(), attempted_path: "employee_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.employee_name())
                }}

    pub fn job_title(&self) -> String {
        self.changed_job_title().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.job_title.clone())
    }

    pub fn update_job_title(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.job_title = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.job_title.clone());
        self.root.set(self.entity_key(), "job_title", value);
        self
    }

    pub fn changed_job_title(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "job_title")
    }

    pub fn eval_job_title(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("job_title") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "job_title".to_string(), attempted_path: "job_title".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.job_title())
                }}

    pub fn hire_date(&self) -> chrono::NaiveDate {
        self.changed_hire_date().and_then(|value| value.try_date()).unwrap_or(self.hire_date)
    }

    pub fn update_hire_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.hire_date = value.try_date().unwrap_or(self.hire_date.clone());
        self.root.set(self.entity_key(), "hire_date", value);
        self
    }

    pub fn changed_hire_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "hire_date")
    }

    pub fn eval_hire_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("hire_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "hire_date".to_string(), attempted_path: "hire_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.hire_date())
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
    pub fn company_profile_id(&self) -> u64 {
        self.changed_company_profile_id().and_then(|value| value.try_u64()).unwrap_or(self.company_profile_id)
    }

    pub fn update_company_profile_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.company_profile_id = value.try_u64().unwrap_or(self.company_profile_id.clone());
        self.root.set(self.entity_key(), "company_profile_id", value);
        self
    }

    pub fn changed_company_profile_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "company_profile_id")
    }

    pub fn eval_company_profile_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("company_profile_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "company_profile_id".to_string(), attempted_path: "company_profile_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.company_profile_id())
                }}
    pub fn company_profile(&self) -> Option<&crate::CompanyProfile> {
        self.company_profile.as_ref()
    }

    pub fn eval_company_profile(&self) -> teaql_core::eval::EvalResult<&crate::CompanyProfile> {
        if !self.is_loaded("company_profile") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "company_profile".to_string(), attempted_path: "company_profile".to_string() }
        } else {
            match &self.company_profile {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }
    pub fn user_account_list(&self) -> &SmartList<crate::UserAccount> {
        &self._relations.user_account_list
    }

    pub fn user_account_list_mut(&mut self) -> &mut SmartList<crate::UserAccount> {
        &mut self._relations.user_account_list
    }

    pub fn eval_user_account_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::UserAccount>> {
        if !self.is_loaded("user_account_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "user_account_list".to_string(), attempted_path: "user_account_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.user_account_list)
        }
    }

    pub fn leave_request_list(&self) -> &SmartList<crate::LeaveRequest> {
        &self._relations.leave_request_list
    }

    pub fn leave_request_list_mut(&mut self) -> &mut SmartList<crate::LeaveRequest> {
        &mut self._relations.leave_request_list
    }

    pub fn eval_leave_request_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::LeaveRequest>> {
        if !self.is_loaded("leave_request_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "leave_request_list".to_string(), attempted_path: "leave_request_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.leave_request_list)
        }
    }

    pub fn payroll_calculation_list(&self) -> &SmartList<crate::PayrollCalculation> {
        &self._relations.payroll_calculation_list
    }

    pub fn payroll_calculation_list_mut(&mut self) -> &mut SmartList<crate::PayrollCalculation> {
        &mut self._relations.payroll_calculation_list
    }

    pub fn eval_payroll_calculation_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::PayrollCalculation>> {
        if !self.is_loaded("payroll_calculation_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "payroll_calculation_list".to_string(), attempted_path: "payroll_calculation_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.payroll_calculation_list)
        }
    }

    pub fn bonus_record_list(&self) -> &SmartList<crate::BonusRecord> {
        &self._relations.bonus_record_list
    }

    pub fn bonus_record_list_mut(&mut self) -> &mut SmartList<crate::BonusRecord> {
        &mut self._relations.bonus_record_list
    }

    pub fn eval_bonus_record_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::BonusRecord>> {
        if !self.is_loaded("bonus_record_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "bonus_record_list".to_string(), attempted_path: "bonus_record_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.bonus_record_list)
        }
    }

    pub fn job_assignment_list(&self) -> &SmartList<crate::JobAssignment> {
        &self._relations.job_assignment_list
    }

    pub fn job_assignment_list_mut(&mut self) -> &mut SmartList<crate::JobAssignment> {
        &mut self._relations.job_assignment_list
    }

    pub fn eval_job_assignment_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::JobAssignment>> {
        if !self.is_loaded("job_assignment_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "job_assignment_list".to_string(), attempted_path: "job_assignment_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.job_assignment_list)
        }
    }

    pub fn worked_hours_list(&self) -> &SmartList<crate::WorkedHours> {
        &self._relations.worked_hours_list
    }

    pub fn worked_hours_list_mut(&mut self) -> &mut SmartList<crate::WorkedHours> {
        &mut self._relations.worked_hours_list
    }

    pub fn eval_worked_hours_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::WorkedHours>> {
        if !self.is_loaded("worked_hours_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "worked_hours_list".to_string(), attempted_path: "worked_hours_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.worked_hours_list)
        }
    }

    pub fn customer_profile_list(&self) -> &SmartList<crate::CustomerProfile> {
        &self._relations.customer_profile_list
    }

    pub fn customer_profile_list_mut(&mut self) -> &mut SmartList<crate::CustomerProfile> {
        &mut self._relations.customer_profile_list
    }

    pub fn eval_customer_profile_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::CustomerProfile>> {
        if !self.is_loaded("customer_profile_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "customer_profile_list".to_string(), attempted_path: "customer_profile_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.customer_profile_list)
        }
    }

    pub fn interaction_history_list(&self) -> &SmartList<crate::InteractionHistory> {
        &self._relations.interaction_history_list
    }

    pub fn interaction_history_list_mut(&mut self) -> &mut SmartList<crate::InteractionHistory> {
        &mut self._relations.interaction_history_list
    }

    pub fn eval_interaction_history_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::InteractionHistory>> {
        if !self.is_loaded("interaction_history_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "interaction_history_list".to_string(), attempted_path: "interaction_history_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.interaction_history_list)
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

#[derive(Clone, Debug, PartialEq, teaql_macros::TeaqlReverseRelations)]
pub struct EmployeeRegistryReverseRelations {
#[teaql(relation(target = "UserAccount", local_key = "id", foreign_key = "employee_registry_id", many))]
    user_account_list: SmartList<crate::UserAccount>,
#[teaql(relation(target = "LeaveRequest", local_key = "id", foreign_key = "employee_record_id", many))]
    leave_request_list: SmartList<crate::LeaveRequest>,
#[teaql(relation(target = "PayrollCalculation", local_key = "id", foreign_key = "employee_record_id", many))]
    payroll_calculation_list: SmartList<crate::PayrollCalculation>,
#[teaql(relation(target = "BonusRecord", local_key = "id", foreign_key = "employee_record_id", many))]
    bonus_record_list: SmartList<crate::BonusRecord>,
#[teaql(relation(target = "JobAssignment", local_key = "id", foreign_key = "employee_record_id", many))]
    job_assignment_list: SmartList<crate::JobAssignment>,
#[teaql(relation(target = "WorkedHours", local_key = "id", foreign_key = "employee_record_id", many))]
    worked_hours_list: SmartList<crate::WorkedHours>,
#[teaql(relation(target = "CustomerProfile", local_key = "id", foreign_key = "account_manager_id", many))]
    customer_profile_list: SmartList<crate::CustomerProfile>,
#[teaql(relation(target = "InteractionHistory", local_key = "id", foreign_key = "employee_record_id", many))]
    interaction_history_list: SmartList<crate::InteractionHistory>,
}

impl EmployeeRegistryReverseRelations {
    pub fn new() -> Self {
        Self {
            user_account_list: Default::default(),
            leave_request_list: Default::default(),
            payroll_calculation_list: Default::default(),
            bonus_record_list: Default::default(),
            job_assignment_list: Default::default(),
            worked_hours_list: Default::default(),
            customer_profile_list: Default::default(),
            interaction_history_list: Default::default(),
        }
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        for entity in &mut self.user_account_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.leave_request_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.payroll_calculation_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.bonus_record_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.job_assignment_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.worked_hours_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.customer_profile_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.interaction_history_list {
            entity.attach_root_recursive(root.clone());
        }
    }
}
