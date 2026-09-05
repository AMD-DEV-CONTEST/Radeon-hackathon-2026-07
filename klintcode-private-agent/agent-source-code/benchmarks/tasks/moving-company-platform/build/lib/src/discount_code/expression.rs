#[derive(Clone)]
pub struct DiscountCodeExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::DiscountCode>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> DiscountCodeExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::DiscountCode>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::DiscountCode> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::DiscountCode> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::DiscountCode {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_code_value(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("code_value", |entity| entity.eval_code_value());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_discount_percent(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("discount_percent", |entity| entity.eval_discount_percent());
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
pub struct DiscountCodeListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::DiscountCode>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> DiscountCodeListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::DiscountCode>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::DiscountCode>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::DiscountCode>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::DiscountCode> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::DiscountCodeExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::DiscountCodeExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::DiscountCodeExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::DiscountCodeExpression::new(next, self.root_desc.clone())
    }
}