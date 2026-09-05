
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/company_profile
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
#[teaql(entity = "CompanyProfile", table = "company_profile_data", data_service = "sqlite")]
pub struct CompanyProfile {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:26
    company_name: String,

// @source moving-company.xml:26
    create_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
    #[teaql(boxed_relations)]
    pub _relations: Box<CompanyProfileReverseRelations>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl CompanyProfile {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            company_name: String::new(),
            create_time: chrono::Utc::now(),
            version: 0_i64,
            _relations: Box::new(CompanyProfileReverseRelations::new()),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("CompanyProfile", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        self._relations.attach_root_recursive(root.clone());
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

    pub fn company_name(&self) -> String {
        self.changed_company_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.company_name.clone())
    }

    pub fn update_company_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.company_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.company_name.clone());
        self.root.set(self.entity_key(), "company_name", value);
        self
    }

    pub fn changed_company_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "company_name")
    }

    pub fn eval_company_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("company_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "company_name".to_string(), attempted_path: "company_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.company_name())
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
    pub fn order_status_list(&self) -> &SmartList<crate::OrderStatus> {
        &self._relations.order_status_list
    }

    pub fn order_status_list_mut(&mut self) -> &mut SmartList<crate::OrderStatus> {
        &mut self._relations.order_status_list
    }

    pub fn eval_order_status_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::OrderStatus>> {
        if !self.is_loaded("order_status_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "order_status_list".to_string(), attempted_path: "order_status_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.order_status_list)
        }
    }

    pub fn user_account_list(&self) -> &SmartList<crate::UserAccount> {
        &self._relations.user_account_list
    }

    pub fn user_account_list_mut(&mut self) -> &mut SmartList<crate::UserAccount> {
        &mut self._relations.user_account_list
    }

    pub fn eval_user_account_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::UserAccount>> {
        if !self.is_loaded("user_account_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "user_account_list".to_string(), attempted_path: "user_account_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.user_account_list)
        }
    }

    pub fn role_definition_list(&self) -> &SmartList<crate::RoleDefinition> {
        &self._relations.role_definition_list
    }

    pub fn role_definition_list_mut(&mut self) -> &mut SmartList<crate::RoleDefinition> {
        &mut self._relations.role_definition_list
    }

    pub fn eval_role_definition_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::RoleDefinition>> {
        if !self.is_loaded("role_definition_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "role_definition_list".to_string(), attempted_path: "role_definition_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.role_definition_list)
        }
    }

    pub fn employee_registry_list(&self) -> &SmartList<crate::EmployeeRegistry> {
        &self._relations.employee_registry_list
    }

    pub fn employee_registry_list_mut(&mut self) -> &mut SmartList<crate::EmployeeRegistry> {
        &mut self._relations.employee_registry_list
    }

    pub fn eval_employee_registry_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::EmployeeRegistry>> {
        if !self.is_loaded("employee_registry_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "employee_registry_list".to_string(), attempted_path: "employee_registry_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.employee_registry_list)
        }
    }

    pub fn marketing_campaign_list(&self) -> &SmartList<crate::MarketingCampaign> {
        &self._relations.marketing_campaign_list
    }

    pub fn marketing_campaign_list_mut(&mut self) -> &mut SmartList<crate::MarketingCampaign> {
        &mut self._relations.marketing_campaign_list
    }

    pub fn eval_marketing_campaign_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::MarketingCampaign>> {
        if !self.is_loaded("marketing_campaign_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "marketing_campaign_list".to_string(), attempted_path: "marketing_campaign_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.marketing_campaign_list)
        }
    }

    pub fn location_address_list(&self) -> &SmartList<crate::LocationAddress> {
        &self._relations.location_address_list
    }

    pub fn location_address_list_mut(&mut self) -> &mut SmartList<crate::LocationAddress> {
        &mut self._relations.location_address_list
    }

    pub fn eval_location_address_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::LocationAddress>> {
        if !self.is_loaded("location_address_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "location_address_list".to_string(), attempted_path: "location_address_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.location_address_list)
        }
    }

    pub fn fleet_vehicle_list(&self) -> &SmartList<crate::FleetVehicle> {
        &self._relations.fleet_vehicle_list
    }

    pub fn fleet_vehicle_list_mut(&mut self) -> &mut SmartList<crate::FleetVehicle> {
        &mut self._relations.fleet_vehicle_list
    }

    pub fn eval_fleet_vehicle_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::FleetVehicle>> {
        if !self.is_loaded("fleet_vehicle_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "fleet_vehicle_list".to_string(), attempted_path: "fleet_vehicle_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.fleet_vehicle_list)
        }
    }

    pub fn service_catalog_list(&self) -> &SmartList<crate::ServiceCatalog> {
        &self._relations.service_catalog_list
    }

    pub fn service_catalog_list_mut(&mut self) -> &mut SmartList<crate::ServiceCatalog> {
        &mut self._relations.service_catalog_list
    }

    pub fn eval_service_catalog_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ServiceCatalog>> {
        if !self.is_loaded("service_catalog_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_catalog_list".to_string(), attempted_path: "service_catalog_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.service_catalog_list)
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

#[derive(Clone, Debug, PartialEq, teaql_macros::TeaqlReverseRelations)]
pub struct CompanyProfileReverseRelations {
#[teaql(relation(target = "OrderStatus", local_key = "id", foreign_key = "company_profile_id", many))]
    order_status_list: SmartList<crate::OrderStatus>,
#[teaql(relation(target = "UserAccount", local_key = "id", foreign_key = "company_profile_id", many))]
    user_account_list: SmartList<crate::UserAccount>,
#[teaql(relation(target = "RoleDefinition", local_key = "id", foreign_key = "company_profile_id", many))]
    role_definition_list: SmartList<crate::RoleDefinition>,
#[teaql(relation(target = "EmployeeRegistry", local_key = "id", foreign_key = "company_profile_id", many))]
    employee_registry_list: SmartList<crate::EmployeeRegistry>,
#[teaql(relation(target = "MarketingCampaign", local_key = "id", foreign_key = "company_profile_id", many))]
    marketing_campaign_list: SmartList<crate::MarketingCampaign>,
#[teaql(relation(target = "LocationAddress", local_key = "id", foreign_key = "company_profile_id", many))]
    location_address_list: SmartList<crate::LocationAddress>,
#[teaql(relation(target = "FleetVehicle", local_key = "id", foreign_key = "company_profile_id", many))]
    fleet_vehicle_list: SmartList<crate::FleetVehicle>,
#[teaql(relation(target = "ServiceCatalog", local_key = "id", foreign_key = "company_profile_id", many))]
    service_catalog_list: SmartList<crate::ServiceCatalog>,
}

impl CompanyProfileReverseRelations {
    pub fn new() -> Self {
        Self {
            order_status_list: Default::default(),
            user_account_list: Default::default(),
            role_definition_list: Default::default(),
            employee_registry_list: Default::default(),
            marketing_campaign_list: Default::default(),
            location_address_list: Default::default(),
            fleet_vehicle_list: Default::default(),
            service_catalog_list: Default::default(),
        }
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        for entity in &mut self.order_status_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.user_account_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.role_definition_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.employee_registry_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.marketing_campaign_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.location_address_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.fleet_vehicle_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.service_catalog_list {
            entity.attach_root_recursive(root.clone());
        }
    }
}
