// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/financial_summary
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "FinancialSummary", table = "financial_summary_data", data_service = "sqlite")]
pub struct FinancialSummary {
#[teaql(id)]
    id: u64,

// @source finance.xml:55
    period: String,

// @source finance.xml:55
    revenue: rust_decimal::Decimal,

// @source finance.xml:55
    expenses: rust_decimal::Decimal,

// @source finance.xml:55
    net_profit: rust_decimal::Decimal,

// @source finance.xml:55
    create_time: chrono::DateTime<chrono::Utc>,

// @source finance.xml:55
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl FinancialSummary {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            period: String::new(),
            revenue: rust_decimal::Decimal::ZERO,
            expenses: rust_decimal::Decimal::ZERO,
            net_profit: rust_decimal::Decimal::ZERO,
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("FinancialSummary", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
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

    pub fn period(&self) -> String {
        self.changed_period().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.period.clone())
    }

    pub fn update_period(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.period = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.period.clone());
        self.root.set(self.entity_key(), "period", value);
        self
    }

    pub fn changed_period(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "period")
    }

    pub fn eval_period(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("period") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "period".to_string(), attempted_path: "period".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.period())
                }}

    pub fn revenue(&self) -> rust_decimal::Decimal {
        self.changed_revenue().and_then(|value| value.try_decimal()).unwrap_or(self.revenue)
    }

    pub fn update_revenue(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.revenue = value.try_decimal().unwrap_or(self.revenue.clone());
        self.root.set(self.entity_key(), "revenue", value);
        self
    }

    pub fn changed_revenue(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "revenue")
    }

    pub fn eval_revenue(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("revenue") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "revenue".to_string(), attempted_path: "revenue".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.revenue())
                }}

    pub fn expenses(&self) -> rust_decimal::Decimal {
        self.changed_expenses().and_then(|value| value.try_decimal()).unwrap_or(self.expenses)
    }

    pub fn update_expenses(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.expenses = value.try_decimal().unwrap_or(self.expenses.clone());
        self.root.set(self.entity_key(), "expenses", value);
        self
    }

    pub fn changed_expenses(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "expenses")
    }

    pub fn eval_expenses(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("expenses") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "expenses".to_string(), attempted_path: "expenses".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.expenses())
                }}

    pub fn net_profit(&self) -> rust_decimal::Decimal {
        self.changed_net_profit().and_then(|value| value.try_decimal()).unwrap_or(self.net_profit)
    }

    pub fn update_net_profit(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.net_profit = value.try_decimal().unwrap_or(self.net_profit.clone());
        self.root.set(self.entity_key(), "net_profit", value);
        self
    }

    pub fn changed_net_profit(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "net_profit")
    }

    pub fn eval_net_profit(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("net_profit") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "net_profit".to_string(), attempted_path: "net_profit".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.net_profit())
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::FinancialSummaryRepository<'a>>>
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
            .financial_summary_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("FinancialSummary"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

