
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

// @source moving-company.xml:218
    campaign_name: String,

// @source moving-company.xml:218
    start_date: chrono::NaiveDate,

// @source moving-company.xml:218
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:218
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:218
#[teaql(column = "company")]
    company_id: u64,
// @source moving-company.xml:218
#[teaql(relation(target = "Company", local_key = "company_id", foreign_key = "id"))]
    company: Option<crate::Company>,
#[teaql(relation(target = "DiscountCode", local_key = "id", foreign_key = "marketing_campaign_id", many))]
    discount_code_list: SmartList<crate::DiscountCode>,
#[teaql(relation(target = "LeadTracking", local_key = "id", foreign_key = "marketing_campaign_id", many))]
    lead_tracking_list: SmartList<crate::LeadTracking>,
#[teaql(relation(target = "ConversionMetric", local_key = "id", foreign_key = "marketing_campaign_id", many))]
    conversion_metric_list: SmartList<crate::ConversionMetric>,
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
            start_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            company_id: 0_u64,
            company: None,
            discount_code_list: Default::default(),
            lead_tracking_list: Default::default(),
            conversion_metric_list: Default::default(),
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
        if let Some(entity) = &mut self.company {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.discount_code_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.lead_tracking_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.conversion_metric_list {
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

    pub fn start_date(&self) -> chrono::NaiveDate {
        self.changed_start_date().and_then(|value| value.try_date()).unwrap_or(self.start_date)
    }

    pub fn update_start_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.start_date = value.try_date().unwrap_or(self.start_date.clone());
        self.root.set(self.entity_key(), "start_date", value);
        self
    }

    pub fn changed_start_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "start_date")
    }

    pub fn eval_start_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("start_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "start_date".to_string(), attempted_path: "start_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.start_date())
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
    pub fn company_id(&self) -> u64 {
        self.changed_company_id().and_then(|value| value.try_u64()).unwrap_or(self.company_id)
    }

    pub fn update_company_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.company_id = value.try_u64().unwrap_or(self.company_id.clone());
        self.root.set(self.entity_key(), "company_id", value);
        self
    }

    pub fn changed_company_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "company_id")
    }

    pub fn eval_company_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("company_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "company_id".to_string(), attempted_path: "company_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.company_id())
                }}
    pub fn company(&self) -> Option<&crate::Company> {
        self.company.as_ref()
    }

    pub fn eval_company(&self) -> teaql_core::eval::EvalResult<&crate::Company> {
        if !self.is_loaded("company") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "company".to_string(), attempted_path: "company".to_string() }
        } else {
            match &self.company {
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

    pub fn lead_tracking_list(&self) -> &SmartList<crate::LeadTracking> {
        &self.lead_tracking_list
    }

    pub fn lead_tracking_list_mut(&mut self) -> &mut SmartList<crate::LeadTracking> {
        &mut self.lead_tracking_list
    }

    pub fn eval_lead_tracking_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::LeadTracking>> {
        if !self.is_loaded("lead_tracking_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "lead_tracking_list".to_string(), attempted_path: "lead_tracking_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.lead_tracking_list)
        }
    }

    pub fn conversion_metric_list(&self) -> &SmartList<crate::ConversionMetric> {
        &self.conversion_metric_list
    }

    pub fn conversion_metric_list_mut(&mut self) -> &mut SmartList<crate::ConversionMetric> {
        &mut self.conversion_metric_list
    }

    pub fn eval_conversion_metric_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ConversionMetric>> {
        if !self.is_loaded("conversion_metric_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "conversion_metric_list".to_string(), attempted_path: "conversion_metric_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.conversion_metric_list)
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

