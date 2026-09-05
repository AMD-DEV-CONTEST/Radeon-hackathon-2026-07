
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/marketing_campaign
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
#[teaql(entity = "MarketingCampaign", table = "marketing_campaign_data", data_service = "sqlite")]
pub struct MarketingCampaign {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:203
    campaign_name: String,

// @source moving-company.xml:203
    target_audience: String,

// @source moving-company.xml:203
    budget_amount: rust_decimal::Decimal,

// @source moving-company.xml:203
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:203
#[teaql(column = "company_profile")]
    company_profile_id: u64,
// @source moving-company.xml:203
#[teaql(relation(target = "CompanyProfile", local_key = "company_profile_id", foreign_key = "id"))]
    company_profile: Option<crate::CompanyProfile>,
#[teaql(relation(target = "DiscountCode", local_key = "id", foreign_key = "marketing_campaign_id", many))]
    discount_code_list: SmartList<crate::DiscountCode>,
#[teaql(relation(target = "SalesLead", local_key = "id", foreign_key = "marketing_campaign_id", many))]
    sales_lead_list: SmartList<crate::SalesLead>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl MarketingCampaign {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            campaign_name: String::new(),
            target_audience: String::new(),
            budget_amount: rust_decimal::Decimal::ZERO,
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            company_profile_id: 0_u64,
            company_profile: None,
            discount_code_list: Default::default(),
            sales_lead_list: Default::default(),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("MarketingCampaign", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.company_profile {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.discount_code_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.sales_lead_list {
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

    pub fn campaign_name(&self) -> String {
        self.changed_campaign_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.campaign_name.clone())
    }

    pub fn update_campaign_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.campaign_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.campaign_name.clone());
        self.root.set(self.entity_key(), "campaign_name", value);
        self
    }

    pub fn changed_campaign_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "campaign_name")
    }

    pub fn eval_campaign_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("campaign_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "campaign_name".to_string(), attempted_path: "campaign_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.campaign_name())
                }}

    pub fn target_audience(&self) -> String {
        self.changed_target_audience().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.target_audience.clone())
    }

    pub fn update_target_audience(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.target_audience = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.target_audience.clone());
        self.root.set(self.entity_key(), "target_audience", value);
        self
    }

    pub fn changed_target_audience(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "target_audience")
    }

    pub fn eval_target_audience(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("target_audience") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "target_audience".to_string(), attempted_path: "target_audience".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.target_audience())
                }}

    pub fn budget_amount(&self) -> rust_decimal::Decimal {
        self.changed_budget_amount().and_then(|value| value.try_decimal()).unwrap_or(self.budget_amount)
    }

    pub fn update_budget_amount(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.budget_amount = value.try_decimal().unwrap_or(self.budget_amount.clone());
        self.root.set(self.entity_key(), "budget_amount", value);
        self
    }

    pub fn changed_budget_amount(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "budget_amount")
    }

    pub fn eval_budget_amount(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("budget_amount") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "budget_amount".to_string(), attempted_path: "budget_amount".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.budget_amount())
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
    pub fn discount_code_list(&self) -> &SmartList<crate::DiscountCode> {
        &self.discount_code_list
    }

    pub fn discount_code_list_mut(&mut self) -> &mut SmartList<crate::DiscountCode> {
        &mut self.discount_code_list
    }

    pub fn eval_discount_code_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::DiscountCode>> {
        if !self.is_loaded("discount_code_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "discount_code_list".to_string(), attempted_path: "discount_code_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.discount_code_list)
        }
    }

    pub fn sales_lead_list(&self) -> &SmartList<crate::SalesLead> {
        &self.sales_lead_list
    }

    pub fn sales_lead_list_mut(&mut self) -> &mut SmartList<crate::SalesLead> {
        &mut self.sales_lead_list
    }

    pub fn eval_sales_lead_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::SalesLead>> {
        if !self.is_loaded("sales_lead_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "sales_lead_list".to_string(), attempted_path: "sales_lead_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.sales_lead_list)
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

