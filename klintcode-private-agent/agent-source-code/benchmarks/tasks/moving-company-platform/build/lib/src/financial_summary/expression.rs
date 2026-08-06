#[derive(Clone)]
pub struct FinancialSummaryExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::FinancialSummary>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> FinancialSummaryExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::FinancialSummary>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::FinancialSummary> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::FinancialSummary> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::FinancialSummary {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_total_revenue(self) -> crate::ValueExpression<'a, rust_decimal::Decimal> {
        let next = self.result.and_then("total_revenue", |entity| entity.eval_total_revenue());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_report_month(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("report_month", |entity| entity.eval_report_month());
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
    pub fn get_invoice_document_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("invoice_document_id", |entity| entity.eval_invoice_document_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_invoice_document(self) -> crate::InvoiceDocumentExpression<'a> {
        let next = self.result.and_then("invoice_document", |entity| entity.eval_invoice_document());
        crate::InvoiceDocumentExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct FinancialSummaryListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::FinancialSummary>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> FinancialSummaryListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::FinancialSummary>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::FinancialSummary>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::FinancialSummary>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::FinancialSummary> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::FinancialSummaryExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::FinancialSummaryExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::FinancialSummaryExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::FinancialSummaryExpression::new(next, self.root_desc.clone())
    }
}