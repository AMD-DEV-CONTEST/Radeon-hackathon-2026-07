#[derive(Clone)]
pub struct CompanyExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::Company>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CompanyExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::Company>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::Company> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::Company> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::Company {
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

    pub fn get_founded_year(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("founded_year", |entity| entity.eval_founded_year());
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
    pub fn get_user_account_list(self) -> crate::UserAccountListExpression<'a> {
        let next = self.result.and_then("user_account_list", |entity| entity.eval_user_account_list());
        crate::UserAccountListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_role_definition_list(self) -> crate::RoleDefinitionListExpression<'a> {
        let next = self.result.and_then("role_definition_list", |entity| entity.eval_role_definition_list());
        crate::RoleDefinitionListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_private_customer_list(self) -> crate::PrivateCustomerListExpression<'a> {
        let next = self.result.and_then("private_customer_list", |entity| entity.eval_private_customer_list());
        crate::PrivateCustomerListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_corporate_customer_list(self) -> crate::CorporateCustomerListExpression<'a> {
        let next = self.result.and_then("corporate_customer_list", |entity| entity.eval_corporate_customer_list());
        crate::CorporateCustomerListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_vehicle_asset_list(self) -> crate::VehicleAssetListExpression<'a> {
        let next = self.result.and_then("vehicle_asset_list", |entity| entity.eval_vehicle_asset_list());
        crate::VehicleAssetListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_consumable_item_list(self) -> crate::ConsumableItemListExpression<'a> {
        let next = self.result.and_then("consumable_item_list", |entity| entity.eval_consumable_item_list());
        crate::ConsumableItemListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_address_record_list(self) -> crate::AddressRecordListExpression<'a> {
        let next = self.result.and_then("address_record_list", |entity| entity.eval_address_record_list());
        crate::AddressRecordListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_service_catalog_list(self) -> crate::ServiceCatalogListExpression<'a> {
        let next = self.result.and_then("service_catalog_list", |entity| entity.eval_service_catalog_list());
        crate::ServiceCatalogListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_marketing_campaign_list(self) -> crate::MarketingCampaignListExpression<'a> {
        let next = self.result.and_then("marketing_campaign_list", |entity| entity.eval_marketing_campaign_list());
        crate::MarketingCampaignListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct CompanyListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Company>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> CompanyListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::Company>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::Company>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::Company>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::Company> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::CompanyExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CompanyExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::CompanyExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::CompanyExpression::new(next, self.root_desc.clone())
    }
}