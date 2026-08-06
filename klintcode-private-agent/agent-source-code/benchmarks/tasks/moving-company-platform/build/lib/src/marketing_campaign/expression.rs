#[derive(Clone)]
pub struct MarketingCampaignExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::MarketingCampaign>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> MarketingCampaignExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::MarketingCampaign>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::MarketingCampaign> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::MarketingCampaign> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::MarketingCampaign {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_campaign_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("campaign_name", |entity| entity.eval_campaign_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_target_audience(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("target_audience", |entity| entity.eval_target_audience());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_budget_amount(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("budget_amount", |entity| entity.eval_budget_amount());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, teaql_core::time::Timestamp> {
        let next = self.result.and_then("create_time", |entity| entity.eval_create_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_version(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("version", |entity| entity.eval_version());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company_profile_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("company_profile_id", |entity| entity.eval_company_profile_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company_profile(self) -> crate::CompanyProfileExpression<'a> {
        let next = self.result.and_then("company_profile", |entity| entity.eval_company_profile());
        crate::CompanyProfileExpression::new(next, self.root_desc.clone())
    }
    pub fn get_discount_code_list(self) -> crate::DiscountCodeListExpression<'a> {
        let next = self.result.and_then("discount_code_list", |entity| entity.eval_discount_code_list());
        crate::DiscountCodeListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_sales_lead_list(self) -> crate::SalesLeadListExpression<'a> {
        let next = self.result.and_then("sales_lead_list", |entity| entity.eval_sales_lead_list());
        crate::SalesLeadListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct MarketingCampaignListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::MarketingCampaign>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> MarketingCampaignListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::MarketingCampaign>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::MarketingCampaign>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::MarketingCampaign>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::MarketingCampaign> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::MarketingCampaignExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::MarketingCampaignExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::MarketingCampaignExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::MarketingCampaignExpression::new(next, self.root_desc.clone())
    }
}