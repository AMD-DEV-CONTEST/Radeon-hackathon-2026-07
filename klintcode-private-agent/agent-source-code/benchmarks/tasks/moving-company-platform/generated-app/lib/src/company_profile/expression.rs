#[derive(Clone)]
pub struct CompanyProfileExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::CompanyProfile>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CompanyProfileExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::CompanyProfile>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::CompanyProfile> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::CompanyProfile> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::CompanyProfile {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_company_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("company_name", |entity| entity.eval_company_name());
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
    pub fn get_order_status_list(self) -> crate::OrderStatusListExpression<'a> {
        let next = self.result.and_then("order_status_list", |entity| entity.eval_order_status_list());
        crate::OrderStatusListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_user_account_list(self) -> crate::UserAccountListExpression<'a> {
        let next = self.result.and_then("user_account_list", |entity| entity.eval_user_account_list());
        crate::UserAccountListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_role_definition_list(self) -> crate::RoleDefinitionListExpression<'a> {
        let next = self.result.and_then("role_definition_list", |entity| entity.eval_role_definition_list());
        crate::RoleDefinitionListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_employee_registry_list(self) -> crate::EmployeeRegistryListExpression<'a> {
        let next = self.result.and_then("employee_registry_list", |entity| entity.eval_employee_registry_list());
        crate::EmployeeRegistryListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_marketing_campaign_list(self) -> crate::MarketingCampaignListExpression<'a> {
        let next = self.result.and_then("marketing_campaign_list", |entity| entity.eval_marketing_campaign_list());
        crate::MarketingCampaignListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_location_address_list(self) -> crate::LocationAddressListExpression<'a> {
        let next = self.result.and_then("location_address_list", |entity| entity.eval_location_address_list());
        crate::LocationAddressListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_fleet_vehicle_list(self) -> crate::FleetVehicleListExpression<'a> {
        let next = self.result.and_then("fleet_vehicle_list", |entity| entity.eval_fleet_vehicle_list());
        crate::FleetVehicleListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_service_catalog_list(self) -> crate::ServiceCatalogListExpression<'a> {
        let next = self.result.and_then("service_catalog_list", |entity| entity.eval_service_catalog_list());
        crate::ServiceCatalogListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct CompanyProfileListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::CompanyProfile>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CompanyProfileListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::CompanyProfile>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::CompanyProfile>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::CompanyProfile>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::CompanyProfile> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::CompanyProfileExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CompanyProfileExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::CompanyProfileExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CompanyProfileExpression::new(next, self.root_desc.clone())
    }
}