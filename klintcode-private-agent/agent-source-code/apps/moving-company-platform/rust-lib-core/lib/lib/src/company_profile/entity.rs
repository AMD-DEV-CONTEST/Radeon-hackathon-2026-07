
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

// @source operations.xml:28
    company_name: String,

// @source operations.xml:28
    registration_number: String,

// @source operations.xml:28
    create_time: teaql_core::time::Timestamp,

// @source operations.xml:28
    update_time: teaql_core::time::Timestamp,
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
    pub const ENTITY_NAME: &'static str = "Company Profile";

    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            company_name: String::new(),
            registration_number: String::new(),
            create_time: teaql_core::time::Timestamp::now(),
            update_time: teaql_core::time::Timestamp::now(),
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

    pub fn registration_number(&self) -> String {
        self.changed_registration_number().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.registration_number.clone())
    }

    pub fn update_registration_number(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.registration_number = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.registration_number.clone());
        self.root.set(self.entity_key(), "registration_number", value);
        self
    }

    pub fn changed_registration_number(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "registration_number")
    }

    pub fn eval_registration_number(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("registration_number") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "registration_number".to_string(), attempted_path: "registration_number".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.registration_number())
                }}

    pub fn create_time(&self) -> teaql_core::time::Timestamp {
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

    pub fn eval_create_time(&self) -> teaql_core::eval::EvalResult<teaql_core::time::Timestamp> {
        if !self.is_loaded("create_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "create_time".to_string(), attempted_path: "create_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.create_time())
                }}

    pub fn update_time(&self) -> teaql_core::time::Timestamp {
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

    pub fn eval_update_time(&self) -> teaql_core::eval::EvalResult<teaql_core::time::Timestamp> {
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
    pub fn move_status_list(&self) -> &SmartList<crate::MoveStatus> {
        &self._relations.move_status_list
    }

    pub fn move_status_list_mut(&mut self) -> &mut SmartList<crate::MoveStatus> {
        &mut self._relations.move_status_list
    }

    pub fn eval_move_status_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::MoveStatus>> {
        if !self.is_loaded("move_status_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_status_list".to_string(), attempted_path: "move_status_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.move_status_list)
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

    pub fn job_title_list(&self) -> &SmartList<crate::JobTitle> {
        &self._relations.job_title_list
    }

    pub fn job_title_list_mut(&mut self) -> &mut SmartList<crate::JobTitle> {
        &mut self._relations.job_title_list
    }

    pub fn eval_job_title_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::JobTitle>> {
        if !self.is_loaded("job_title_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "job_title_list".to_string(), attempted_path: "job_title_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.job_title_list)
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

    pub fn customer_type_list(&self) -> &SmartList<crate::CustomerType> {
        &self._relations.customer_type_list
    }

    pub fn customer_type_list_mut(&mut self) -> &mut SmartList<crate::CustomerType> {
        &mut self._relations.customer_type_list
    }

    pub fn eval_customer_type_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::CustomerType>> {
        if !self.is_loaded("customer_type_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "customer_type_list".to_string(), attempted_path: "customer_type_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.customer_type_list)
        }
    }

    pub fn service_category_list(&self) -> &SmartList<crate::ServiceCategory> {
        &self._relations.service_category_list
    }

    pub fn service_category_list_mut(&mut self) -> &mut SmartList<crate::ServiceCategory> {
        &mut self._relations.service_category_list
    }

    pub fn eval_service_category_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ServiceCategory>> {
        if !self.is_loaded("service_category_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_category_list".to_string(), attempted_path: "service_category_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.service_category_list)
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

    pub fn service_bundle_list(&self) -> &SmartList<crate::ServiceBundle> {
        &self._relations.service_bundle_list
    }

    pub fn service_bundle_list_mut(&mut self) -> &mut SmartList<crate::ServiceBundle> {
        &mut self._relations.service_bundle_list
    }

    pub fn eval_service_bundle_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ServiceBundle>> {
        if !self.is_loaded("service_bundle_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_bundle_list".to_string(), attempted_path: "service_bundle_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.service_bundle_list)
        }
    }

    pub fn campaign_status_list(&self) -> &SmartList<crate::CampaignStatus> {
        &self._relations.campaign_status_list
    }

    pub fn campaign_status_list_mut(&mut self) -> &mut SmartList<crate::CampaignStatus> {
        &mut self._relations.campaign_status_list
    }

    pub fn eval_campaign_status_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::CampaignStatus>> {
        if !self.is_loaded("campaign_status_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "campaign_status_list".to_string(), attempted_path: "campaign_status_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.campaign_status_list)
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

    pub fn payment_method_list(&self) -> &SmartList<crate::PaymentMethod> {
        &self._relations.payment_method_list
    }

    pub fn payment_method_list_mut(&mut self) -> &mut SmartList<crate::PaymentMethod> {
        &mut self._relations.payment_method_list
    }

    pub fn eval_payment_method_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::PaymentMethod>> {
        if !self.is_loaded("payment_method_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "payment_method_list".to_string(), attempted_path: "payment_method_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.payment_method_list)
        }
    }

    pub fn vehicle_type_list(&self) -> &SmartList<crate::VehicleType> {
        &self._relations.vehicle_type_list
    }

    pub fn vehicle_type_list_mut(&mut self) -> &mut SmartList<crate::VehicleType> {
        &mut self._relations.vehicle_type_list
    }

    pub fn eval_vehicle_type_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::VehicleType>> {
        if !self.is_loaded("vehicle_type_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "vehicle_type_list".to_string(), attempted_path: "vehicle_type_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.vehicle_type_list)
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

    pub fn equipment_item_list(&self) -> &SmartList<crate::EquipmentItem> {
        &self._relations.equipment_item_list
    }

    pub fn equipment_item_list_mut(&mut self) -> &mut SmartList<crate::EquipmentItem> {
        &mut self._relations.equipment_item_list
    }

    pub fn eval_equipment_item_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::EquipmentItem>> {
        if !self.is_loaded("equipment_item_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "equipment_item_list".to_string(), attempted_path: "equipment_item_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.equipment_item_list)
        }
    }

    pub fn user_role_list(&self) -> &SmartList<crate::UserRole> {
        &self._relations.user_role_list
    }

    pub fn user_role_list_mut(&mut self) -> &mut SmartList<crate::UserRole> {
        &mut self._relations.user_role_list
    }

    pub fn eval_user_role_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::UserRole>> {
        if !self.is_loaded("user_role_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "user_role_list".to_string(), attempted_path: "user_role_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.user_role_list)
        }
    }

    pub fn notification_type_list(&self) -> &SmartList<crate::NotificationType> {
        &self._relations.notification_type_list
    }

    pub fn notification_type_list_mut(&mut self) -> &mut SmartList<crate::NotificationType> {
        &mut self._relations.notification_type_list
    }

    pub fn eval_notification_type_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::NotificationType>> {
        if !self.is_loaded("notification_type_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "notification_type_list".to_string(), attempted_path: "notification_type_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.notification_type_list)
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
#[teaql(relation(target = "MoveStatus", local_key = "id", foreign_key = "company_profile_id", many))]
    move_status_list: SmartList<crate::MoveStatus>,
#[teaql(relation(target = "LocationAddress", local_key = "id", foreign_key = "company_profile_id", many))]
    location_address_list: SmartList<crate::LocationAddress>,
#[teaql(relation(target = "JobTitle", local_key = "id", foreign_key = "company_profile_id", many))]
    job_title_list: SmartList<crate::JobTitle>,
#[teaql(relation(target = "EmployeeRegistry", local_key = "id", foreign_key = "company_profile_id", many))]
    employee_registry_list: SmartList<crate::EmployeeRegistry>,
#[teaql(relation(target = "CustomerType", local_key = "id", foreign_key = "company_profile_id", many))]
    customer_type_list: SmartList<crate::CustomerType>,
#[teaql(relation(target = "ServiceCategory", local_key = "id", foreign_key = "company_profile_id", many))]
    service_category_list: SmartList<crate::ServiceCategory>,
#[teaql(relation(target = "ServiceCatalog", local_key = "id", foreign_key = "company_profile_id", many))]
    service_catalog_list: SmartList<crate::ServiceCatalog>,
#[teaql(relation(target = "ServiceBundle", local_key = "id", foreign_key = "company_profile_id", many))]
    service_bundle_list: SmartList<crate::ServiceBundle>,
#[teaql(relation(target = "CampaignStatus", local_key = "id", foreign_key = "company_profile_id", many))]
    campaign_status_list: SmartList<crate::CampaignStatus>,
#[teaql(relation(target = "MarketingCampaign", local_key = "id", foreign_key = "company_profile_id", many))]
    marketing_campaign_list: SmartList<crate::MarketingCampaign>,
#[teaql(relation(target = "PaymentMethod", local_key = "id", foreign_key = "company_profile_id", many))]
    payment_method_list: SmartList<crate::PaymentMethod>,
#[teaql(relation(target = "VehicleType", local_key = "id", foreign_key = "company_profile_id", many))]
    vehicle_type_list: SmartList<crate::VehicleType>,
#[teaql(relation(target = "FleetVehicle", local_key = "id", foreign_key = "company_profile_id", many))]
    fleet_vehicle_list: SmartList<crate::FleetVehicle>,
#[teaql(relation(target = "EquipmentItem", local_key = "id", foreign_key = "company_profile_id", many))]
    equipment_item_list: SmartList<crate::EquipmentItem>,
#[teaql(relation(target = "UserRole", local_key = "id", foreign_key = "company_profile_id", many))]
    user_role_list: SmartList<crate::UserRole>,
#[teaql(relation(target = "NotificationType", local_key = "id", foreign_key = "company_profile_id", many))]
    notification_type_list: SmartList<crate::NotificationType>,
#[teaql(relation(target = "UserAccount", local_key = "id", foreign_key = "company_profile_id", many))]
    user_account_list: SmartList<crate::UserAccount>,
#[teaql(relation(target = "RoleDefinition", local_key = "id", foreign_key = "company_profile_id", many))]
    role_definition_list: SmartList<crate::RoleDefinition>,
}

impl CompanyProfileReverseRelations {
    pub fn new() -> Self {
        Self {
            move_status_list: Default::default(),
            location_address_list: Default::default(),
            job_title_list: Default::default(),
            employee_registry_list: Default::default(),
            customer_type_list: Default::default(),
            service_category_list: Default::default(),
            service_catalog_list: Default::default(),
            service_bundle_list: Default::default(),
            campaign_status_list: Default::default(),
            marketing_campaign_list: Default::default(),
            payment_method_list: Default::default(),
            vehicle_type_list: Default::default(),
            fleet_vehicle_list: Default::default(),
            equipment_item_list: Default::default(),
            user_role_list: Default::default(),
            notification_type_list: Default::default(),
            user_account_list: Default::default(),
            role_definition_list: Default::default(),
        }
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        for entity in &mut self.move_status_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.location_address_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.job_title_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.employee_registry_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.customer_type_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.service_category_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.service_catalog_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.service_bundle_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.campaign_status_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.marketing_campaign_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.payment_method_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.vehicle_type_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.fleet_vehicle_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.equipment_item_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.user_role_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.notification_type_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.user_account_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.role_definition_list {
            entity.attach_root_recursive(root.clone());
        }
    }
}
