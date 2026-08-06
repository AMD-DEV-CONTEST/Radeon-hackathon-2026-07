#[derive(Clone)]
pub struct ServiceCatalogExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::ServiceCatalog>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> ServiceCatalogExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::ServiceCatalog>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::ServiceCatalog> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::ServiceCatalog> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::ServiceCatalog {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_service_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("service_name", |entity| entity.eval_service_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_service_description(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("service_description", |entity| entity.eval_service_description());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
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
    pub fn get_service_config_list(self) -> crate::ServiceConfigListExpression<'a> {
        let next = self.result.and_then("service_config_list", |entity| entity.eval_service_config_list());
        crate::ServiceConfigListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_box_rental_list(self) -> crate::BoxRentalListExpression<'a> {
        let next = self.result.and_then("box_rental_list", |entity| entity.eval_box_rental_list());
        crate::BoxRentalListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct ServiceCatalogListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::ServiceCatalog>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> ServiceCatalogListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::ServiceCatalog>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::ServiceCatalog>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::ServiceCatalog>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::ServiceCatalog> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::ServiceCatalogExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::ServiceCatalogExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::ServiceCatalogExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::ServiceCatalogExpression::new(next, self.root_desc.clone())
    }
}