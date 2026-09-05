// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/discount_code
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "DiscountCode", table = "discount_code_data", data_service = "sqlite")]
pub struct DiscountCode {
#[teaql(id)]
    id: u64,

// @source marketing_sales.xml:30
    code: String,

// @source marketing_sales.xml:30
    discount_percent: rust_decimal::Decimal,

// @source marketing_sales.xml:30
    usage_limit: i64,

// @source marketing_sales.xml:30
    used_count: i64,

// @source marketing_sales.xml:30
    valid_from: chrono::NaiveDate,

// @source marketing_sales.xml:30
    valid_to: chrono::NaiveDate,

// @source marketing_sales.xml:30
    create_time: chrono::DateTime<chrono::Utc>,

// @source marketing_sales.xml:30
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

impl DiscountCode {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            code: String::new(),
            discount_percent: rust_decimal::Decimal::ZERO,
            usage_limit: 0_i64,
            used_count: 0_i64,
            valid_from: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            valid_to: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("DiscountCode", self.id)
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

    pub fn code(&self) -> String {
        self.changed_code().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.code.clone())
    }

    pub fn update_code(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.code = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.code.clone());
        self.root.set(self.entity_key(), "code", value);
        self
    }

    pub fn changed_code(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "code")
    }

    pub fn eval_code(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("code") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "code".to_string(), attempted_path: "code".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.code())
                }}

    pub fn discount_percent(&self) -> rust_decimal::Decimal {
        self.changed_discount_percent().and_then(|value| value.try_decimal()).unwrap_or(self.discount_percent)
    }

    pub fn update_discount_percent(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.discount_percent = value.try_decimal().unwrap_or(self.discount_percent.clone());
        self.root.set(self.entity_key(), "discount_percent", value);
        self
    }

    pub fn changed_discount_percent(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "discount_percent")
    }

    pub fn eval_discount_percent(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("discount_percent") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "discount_percent".to_string(), attempted_path: "discount_percent".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.discount_percent())
                }}

    pub fn usage_limit(&self) -> i64 {
        self.changed_usage_limit().and_then(|value| value.try_i64()).map(|value| value as i64).unwrap_or(self.usage_limit)
    }

    pub fn update_usage_limit(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.usage_limit = value.try_i64().map(|value| value as i64).unwrap_or(self.usage_limit.clone());
        self.root.set(self.entity_key(), "usage_limit", value);
        self
    }

    pub fn changed_usage_limit(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "usage_limit")
    }

    pub fn eval_usage_limit(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("usage_limit") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "usage_limit".to_string(), attempted_path: "usage_limit".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.usage_limit())
                }}

    pub fn used_count(&self) -> i64 {
        self.changed_used_count().and_then(|value| value.try_i64()).map(|value| value as i64).unwrap_or(self.used_count)
    }

    pub fn update_used_count(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.used_count = value.try_i64().map(|value| value as i64).unwrap_or(self.used_count.clone());
        self.root.set(self.entity_key(), "used_count", value);
        self
    }

    pub fn changed_used_count(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "used_count")
    }

    pub fn eval_used_count(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("used_count") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "used_count".to_string(), attempted_path: "used_count".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.used_count())
                }}

    pub fn valid_from(&self) -> chrono::NaiveDate {
        self.changed_valid_from().and_then(|value| value.try_date()).unwrap_or(self.valid_from)
    }

    pub fn update_valid_from(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.valid_from = value.try_date().unwrap_or(self.valid_from.clone());
        self.root.set(self.entity_key(), "valid_from", value);
        self
    }

    pub fn changed_valid_from(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "valid_from")
    }

    pub fn eval_valid_from(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("valid_from") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "valid_from".to_string(), attempted_path: "valid_from".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.valid_from())
                }}

    pub fn valid_to(&self) -> chrono::NaiveDate {
        self.changed_valid_to().and_then(|value| value.try_date()).unwrap_or(self.valid_to)
    }

    pub fn update_valid_to(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.valid_to = value.try_date().unwrap_or(self.valid_to.clone());
        self.root.set(self.entity_key(), "valid_to", value);
        self
    }

    pub fn changed_valid_to(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "valid_to")
    }

    pub fn eval_valid_to(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("valid_to") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "valid_to".to_string(), attempted_path: "valid_to".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.valid_to())
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
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
            .discount_code_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("DiscountCode"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

