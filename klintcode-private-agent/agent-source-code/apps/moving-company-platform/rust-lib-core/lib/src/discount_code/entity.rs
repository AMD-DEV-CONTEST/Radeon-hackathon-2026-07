
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

// @source moving-company.xml:224
    code_string: String,

// @source moving-company.xml:224
    discount_percent: rust_decimal::Decimal,

// @source moving-company.xml:224
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:224
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:224
#[teaql(column = "marketing_campaign")]
    marketing_campaign_id: u64,
// @source moving-company.xml:224
#[teaql(relation(target = "MarketingCampaign", local_key = "marketing_campaign_id", foreign_key = "id"))]
    marketing_campaign: Option<crate::MarketingCampaign>,
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
            code_string: String::new(),
            discount_percent: rust_decimal::Decimal::ZERO,
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            marketing_campaign_id: 0_u64,
            marketing_campaign: None,
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
        if let Some(entity) = &mut self.marketing_campaign {
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

    pub fn code_string(&self) -> String {
        self.changed_code_string().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.code_string.clone())
    }

    pub fn update_code_string(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.code_string = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.code_string.clone());
        self.root.set(self.entity_key(), "code_string", value);
        self
    }

    pub fn changed_code_string(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "code_string")
    }

    pub fn eval_code_string(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("code_string") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "code_string".to_string(), attempted_path: "code_string".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.code_string())
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
    pub fn marketing_campaign_id(&self) -> u64 {
        self.changed_marketing_campaign_id().and_then(|value| value.try_u64()).unwrap_or(self.marketing_campaign_id)
    }

    pub fn update_marketing_campaign_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.marketing_campaign_id = value.try_u64().unwrap_or(self.marketing_campaign_id.clone());
        self.root.set(self.entity_key(), "marketing_campaign_id", value);
        self
    }

    pub fn changed_marketing_campaign_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "marketing_campaign_id")
    }

    pub fn eval_marketing_campaign_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("marketing_campaign_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "marketing_campaign_id".to_string(), attempted_path: "marketing_campaign_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.marketing_campaign_id())
                }}
    pub fn marketing_campaign(&self) -> Option<&crate::MarketingCampaign> {
        self.marketing_campaign.as_ref()
    }

    pub fn eval_marketing_campaign(&self) -> teaql_core::eval::EvalResult<&crate::MarketingCampaign> {
        if !self.is_loaded("marketing_campaign") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "marketing_campaign".to_string(), attempted_path: "marketing_campaign".to_string() }
        } else {
            match &self.marketing_campaign {
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

