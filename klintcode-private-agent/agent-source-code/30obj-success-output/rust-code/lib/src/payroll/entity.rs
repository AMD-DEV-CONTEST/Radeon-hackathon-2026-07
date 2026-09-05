// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/payroll
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "Payroll", table = "payroll_data", data_service = "sqlite")]
pub struct Payroll {
#[teaql(id)]
    id: u64,

// @source employees.xml:62
    pay_period_start: chrono::NaiveDate,

// @source employees.xml:62
    pay_period_end: chrono::NaiveDate,

// @source employees.xml:62
    base_salary: rust_decimal::Decimal,

// @source employees.xml:62
    overtime_pay: rust_decimal::Decimal,

// @source employees.xml:62
    bonus: rust_decimal::Decimal,

// @source employees.xml:62
    deductions: rust_decimal::Decimal,

// @source employees.xml:62
    net_pay: rust_decimal::Decimal,

// @source employees.xml:62
    payment_date: chrono::NaiveDate,

// @source employees.xml:62
    create_time: chrono::DateTime<chrono::Utc>,

// @source employees.xml:62
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source employees.xml:62
#[teaql(column = "staff")]
    staff_id: u64,
// @source employees.xml:62
#[teaql(relation(target = "Staff", local_key = "staff_id", foreign_key = "id"))]
    staff: Option<crate::Staff>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl Payroll {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            pay_period_start: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            pay_period_end: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            base_salary: rust_decimal::Decimal::ZERO,
            overtime_pay: rust_decimal::Decimal::ZERO,
            bonus: rust_decimal::Decimal::ZERO,
            deductions: rust_decimal::Decimal::ZERO,
            net_pay: rust_decimal::Decimal::ZERO,
            payment_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
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
        teaql_runtime::EntityKey::new("Payroll", self.id)
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

    pub fn pay_period_start(&self) -> chrono::NaiveDate {
        self.changed_pay_period_start().and_then(|value| value.try_date()).unwrap_or(self.pay_period_start)
    }

    pub fn update_pay_period_start(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.pay_period_start = value.try_date().unwrap_or(self.pay_period_start.clone());
        self.root.set(self.entity_key(), "pay_period_start", value);
        self
    }

    pub fn changed_pay_period_start(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "pay_period_start")
    }

    pub fn eval_pay_period_start(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("pay_period_start") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "pay_period_start".to_string(), attempted_path: "pay_period_start".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.pay_period_start())
                }}

    pub fn pay_period_end(&self) -> chrono::NaiveDate {
        self.changed_pay_period_end().and_then(|value| value.try_date()).unwrap_or(self.pay_period_end)
    }

    pub fn update_pay_period_end(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.pay_period_end = value.try_date().unwrap_or(self.pay_period_end.clone());
        self.root.set(self.entity_key(), "pay_period_end", value);
        self
    }

    pub fn changed_pay_period_end(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "pay_period_end")
    }

    pub fn eval_pay_period_end(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("pay_period_end") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "pay_period_end".to_string(), attempted_path: "pay_period_end".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.pay_period_end())
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

    pub fn overtime_pay(&self) -> rust_decimal::Decimal {
        self.changed_overtime_pay().and_then(|value| value.try_decimal()).unwrap_or(self.overtime_pay)
    }

    pub fn update_overtime_pay(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.overtime_pay = value.try_decimal().unwrap_or(self.overtime_pay.clone());
        self.root.set(self.entity_key(), "overtime_pay", value);
        self
    }

    pub fn changed_overtime_pay(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "overtime_pay")
    }

    pub fn eval_overtime_pay(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("overtime_pay") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "overtime_pay".to_string(), attempted_path: "overtime_pay".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.overtime_pay())
                }}

    pub fn bonus(&self) -> rust_decimal::Decimal {
        self.changed_bonus().and_then(|value| value.try_decimal()).unwrap_or(self.bonus)
    }

    pub fn update_bonus(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.bonus = value.try_decimal().unwrap_or(self.bonus.clone());
        self.root.set(self.entity_key(), "bonus", value);
        self
    }

    pub fn changed_bonus(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "bonus")
    }

    pub fn eval_bonus(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("bonus") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "bonus".to_string(), attempted_path: "bonus".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.bonus())
                }}

    pub fn deductions(&self) -> rust_decimal::Decimal {
        self.changed_deductions().and_then(|value| value.try_decimal()).unwrap_or(self.deductions)
    }

    pub fn update_deductions(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.deductions = value.try_decimal().unwrap_or(self.deductions.clone());
        self.root.set(self.entity_key(), "deductions", value);
        self
    }

    pub fn changed_deductions(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "deductions")
    }

    pub fn eval_deductions(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("deductions") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "deductions".to_string(), attempted_path: "deductions".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.deductions())
                }}

    pub fn net_pay(&self) -> rust_decimal::Decimal {
        self.changed_net_pay().and_then(|value| value.try_decimal()).unwrap_or(self.net_pay)
    }

    pub fn update_net_pay(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.net_pay = value.try_decimal().unwrap_or(self.net_pay.clone());
        self.root.set(self.entity_key(), "net_pay", value);
        self
    }

    pub fn changed_net_pay(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "net_pay")
    }

    pub fn eval_net_pay(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("net_pay") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "net_pay".to_string(), attempted_path: "net_pay".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.net_pay())
                }}

    pub fn payment_date(&self) -> chrono::NaiveDate {
        self.changed_payment_date().and_then(|value| value.try_date()).unwrap_or(self.payment_date)
    }

    pub fn update_payment_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.payment_date = value.try_date().unwrap_or(self.payment_date.clone());
        self.root.set(self.entity_key(), "payment_date", value);
        self
    }

    pub fn changed_payment_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "payment_date")
    }

    pub fn eval_payment_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("payment_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "payment_date".to_string(), attempted_path: "payment_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.payment_date())
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::PayrollRepository<'a>>>
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
            .payroll_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("Payroll"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

