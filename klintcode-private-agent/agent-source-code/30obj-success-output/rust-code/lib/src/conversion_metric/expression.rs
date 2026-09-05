#[derive(Clone)]
pub struct ConversionMetricExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::ConversionMetric>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> ConversionMetricExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::ConversionMetric>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::ConversionMetric> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::ConversionMetric> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::ConversionMetric {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_leads_generated(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("leads_generated", |entity| entity.eval_leads_generated());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_conversions(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("conversions", |entity| entity.eval_conversions());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_conversion_rate(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("conversion_rate", |entity| entity.eval_conversion_rate());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_revenue_attributed(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("revenue_attributed", |entity| entity.eval_revenue_attributed());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_date_recorded(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("date_recorded", |entity| entity.eval_date_recorded());
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
    pub fn get_campaign_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("campaign_id", |entity| entity.eval_campaign_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_campaign(self) -> crate::CampaignExpression<'a> {
        let next = self.result.and_then("campaign", |entity| entity.eval_campaign());
        crate::CampaignExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct ConversionMetricListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::ConversionMetric>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> ConversionMetricListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::ConversionMetric>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::ConversionMetric>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::ConversionMetric>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::ConversionMetric> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::ConversionMetricExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::ConversionMetricExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::ConversionMetricExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::ConversionMetricExpression::new(next, self.root_desc.clone())
    }
}