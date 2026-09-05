#[derive(Clone)]
pub struct LeadTrackingExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::LeadTracking>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> LeadTrackingExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::LeadTracking>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::LeadTracking> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::LeadTracking> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::LeadTracking {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_lead_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("lead_name", |entity| entity.eval_lead_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_lead_status(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("lead_status", |entity| entity.eval_lead_status());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
        let next = self.result.and_then("create_time", |entity| entity.eval_create_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_update_time(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
        let next = self.result.and_then("update_time", |entity| entity.eval_update_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_version(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("version", |entity| entity.eval_version());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_marketing_campaign_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("marketing_campaign_id", |entity| entity.eval_marketing_campaign_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_marketing_campaign(self) -> crate::MarketingCampaignExpression<'a> {
        let next = self.result.and_then("marketing_campaign", |entity| entity.eval_marketing_campaign());
        crate::MarketingCampaignExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct LeadTrackingListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::LeadTracking>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> LeadTrackingListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::LeadTracking>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::LeadTracking>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::LeadTracking>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::LeadTracking> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::LeadTrackingExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::LeadTrackingExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::LeadTrackingExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::LeadTrackingExpression::new(next, self.root_desc.clone())
    }
}