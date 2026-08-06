
use crate::*;
use teaql_core::TeaqlEntity;

use teaql_provider_sqlite::SqliteProviderExt as _;

pub type DataServiceDialect = teaql_provider_sqlite::SqliteDialect;
pub type DataServiceMutationExecutor = teaql_provider_sqlite::SqliteMutationExecutor;
pub type DataServiceMutationError = teaql_provider_sqlite::MutationExecutorError;
pub type DataServiceIdGenerator = teaql_provider_sqlite::SqliteIdSpaceGenerator;
pub type DataServicePool = std::sync::Arc<std::sync::Mutex<rusqlite::Connection>>;
pub type DataServiceExecutor = ServiceRuntimeExecutor;
pub type ServiceRuntime = teaql_runtime::UserContext;

pub const DATABASE_URL_ENV: &str = "MOVING_COMPANY_SERVICE_CORE_DATABASE_URL";
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ServiceRuntimeConfig {
    pub database_url: String,
}

impl ServiceRuntimeConfig {
    pub fn from_env() -> Result<Self, ServiceRuntimeError> {
        Ok(Self {
            database_url: env_value(DATABASE_URL_ENV)?,
        })
    }
}

#[derive(Debug)]
pub enum ServiceRuntimeError {
    MissingEnv {
        name: &'static str,
        source: std::env::VarError,
    },
    ConnectionError(String),
    Rusqlite(rusqlite::Error),
    Runtime(teaql_runtime::RuntimeError),
}

impl std::fmt::Display for ServiceRuntimeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ServiceRuntimeError::MissingEnv { name, source } => {
                write!(f, "missing environment variable {name}: {source}")
            }
            ServiceRuntimeError::ConnectionError(err) => write!(f, "connection error: {err}"),
            ServiceRuntimeError::Rusqlite(err) => write!(f, "rusqlite error: {err}"),
            ServiceRuntimeError::Runtime(err) => write!(f, "runtime error: {err}"),
        }
    }
}

impl std::error::Error for ServiceRuntimeError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            ServiceRuntimeError::MissingEnv { source, .. } => Some(source),
            ServiceRuntimeError::ConnectionError(_) => None,
            ServiceRuntimeError::Rusqlite(err) => Some(err),
            ServiceRuntimeError::Runtime(err) => Some(err),
        }
    }
}

impl From<rusqlite::Error> for ServiceRuntimeError {
    fn from(err: rusqlite::Error) -> Self {
        ServiceRuntimeError::Rusqlite(err)
    }
}
impl From<teaql_runtime::RuntimeError> for ServiceRuntimeError {
    fn from(err: teaql_runtime::RuntimeError) -> Self {
        ServiceRuntimeError::Runtime(err)
    }
}

#[derive(Clone)]
pub struct LocalSchemaProvider;

impl teaql_data_service::SchemaProvider for LocalSchemaProvider {
    fn get_entity(&self, name: &str) -> Option<std::sync::Arc<teaql_core::EntityDescriptor>> {
        match name {
            "Company" => Some(std::sync::Arc::new(crate::Company::entity_descriptor())),
            "UserAccount" => Some(std::sync::Arc::new(crate::UserAccount::entity_descriptor())),
            "RoleDefinition" => Some(std::sync::Arc::new(crate::RoleDefinition::entity_descriptor())),
            "UserRole" => Some(std::sync::Arc::new(crate::UserRole::entity_descriptor())),
            "AuditLog" => Some(std::sync::Arc::new(crate::AuditLog::entity_descriptor())),
            "NotificationRule" => Some(std::sync::Arc::new(crate::NotificationRule::entity_descriptor())),
            "DocumentStorage" => Some(std::sync::Arc::new(crate::DocumentStorage::entity_descriptor())),
            "EmployeeRecord" => Some(std::sync::Arc::new(crate::EmployeeRecord::entity_descriptor())),
            "PayrollCalculation" => Some(std::sync::Arc::new(crate::PayrollCalculation::entity_descriptor())),
            "WorkedHours" => Some(std::sync::Arc::new(crate::WorkedHours::entity_descriptor())),
            "BonusRecord" => Some(std::sync::Arc::new(crate::BonusRecord::entity_descriptor())),
            "LeaveRequest" => Some(std::sync::Arc::new(crate::LeaveRequest::entity_descriptor())),
            "PrivateCustomer" => Some(std::sync::Arc::new(crate::PrivateCustomer::entity_descriptor())),
            "CorporateCustomer" => Some(std::sync::Arc::new(crate::CorporateCustomer::entity_descriptor())),
            "LinkedContact" => Some(std::sync::Arc::new(crate::LinkedContact::entity_descriptor())),
            "BillingInfo" => Some(std::sync::Arc::new(crate::BillingInfo::entity_descriptor())),
            "InteractionHistory" => Some(std::sync::Arc::new(crate::InteractionHistory::entity_descriptor())),
            "VehicleAsset" => Some(std::sync::Arc::new(crate::VehicleAsset::entity_descriptor())),
            "EquipmentItem" => Some(std::sync::Arc::new(crate::EquipmentItem::entity_descriptor())),
            "ConsumableItem" => Some(std::sync::Arc::new(crate::ConsumableItem::entity_descriptor())),
            "MaintenanceSchedule" => Some(std::sync::Arc::new(crate::MaintenanceSchedule::entity_descriptor())),
            "InventoryTracking" => Some(std::sync::Arc::new(crate::InventoryTracking::entity_descriptor())),
            "InsurancePolicy" => Some(std::sync::Arc::new(crate::InsurancePolicy::entity_descriptor())),
            "AddressRecord" => Some(std::sync::Arc::new(crate::AddressRecord::entity_descriptor())),
            "MoveOrder" => Some(std::sync::Arc::new(crate::MoveOrder::entity_descriptor())),
            "RoutePlan" => Some(std::sync::Arc::new(crate::RoutePlan::entity_descriptor())),
            "TimeSlot" => Some(std::sync::Arc::new(crate::TimeSlot::entity_descriptor())),
            "FulfillmentEvent" => Some(std::sync::Arc::new(crate::FulfillmentEvent::entity_descriptor())),
            "JobAssignment" => Some(std::sync::Arc::new(crate::JobAssignment::entity_descriptor())),
            "ServiceCatalog" => Some(std::sync::Arc::new(crate::ServiceCatalog::entity_descriptor())),
            "ServiceConfig" => Some(std::sync::Arc::new(crate::ServiceConfig::entity_descriptor())),
            "BoxRental" => Some(std::sync::Arc::new(crate::BoxRental::entity_descriptor())),
            "MarketingCampaign" => Some(std::sync::Arc::new(crate::MarketingCampaign::entity_descriptor())),
            "DiscountCode" => Some(std::sync::Arc::new(crate::DiscountCode::entity_descriptor())),
            "LeadTracking" => Some(std::sync::Arc::new(crate::LeadTracking::entity_descriptor())),
            "ConversionMetric" => Some(std::sync::Arc::new(crate::ConversionMetric::entity_descriptor())),
            "InvoiceDocument" => Some(std::sync::Arc::new(crate::InvoiceDocument::entity_descriptor())),
            "PaymentRecord" => Some(std::sync::Arc::new(crate::PaymentRecord::entity_descriptor())),
            "ExpenseRecord" => Some(std::sync::Arc::new(crate::ExpenseRecord::entity_descriptor())),
            "VatRecord" => Some(std::sync::Arc::new(crate::VatRecord::entity_descriptor())),
            "FinancialSummary" => Some(std::sync::Arc::new(crate::FinancialSummary::entity_descriptor())),
            "ServiceContract" => Some(std::sync::Arc::new(crate::ServiceContract::entity_descriptor())),
            _ => None,
        }
    }
}

#[derive(Clone)]
pub struct ServiceRuntimeExecutor {
    inner: teaql_sql::SqlDataServiceExecutor<
        DataServiceDialect,
        DataServiceMutationExecutor,
        LocalSchemaProvider
    >,
}

impl ServiceRuntimeExecutor {
    pub fn new(inner: DataServiceMutationExecutor) -> Self {
        Self {
            inner: teaql_sql::SqlDataServiceExecutor::new(
                DataServiceDialect::default(),
                inner,
                LocalSchemaProvider
            ),
        }
    }

}

impl teaql_data_service::DataServiceExecutor for ServiceRuntimeExecutor {
    type Error = teaql_sql::SqlExecutorError<DataServiceMutationError>;
    fn capabilities(&self) -> teaql_data_service::DataServiceCapabilities {
        teaql_data_service::DataServiceExecutor::capabilities(&self.inner)
    }
}

impl teaql_data_service::QueryExecutor for ServiceRuntimeExecutor {
    async fn query(&self, request: teaql_data_service::QueryRequest) -> Result<teaql_data_service::QueryResult, Self::Error> {
        teaql_data_service::QueryExecutor::query(&self.inner, request).await
    }
}

impl teaql_data_service::StreamQueryExecutor for ServiceRuntimeExecutor {
    async fn query_stream(&self, request: teaql_data_service::QueryRequest, chunk_size: usize) -> Result<Vec<teaql_data_service::StreamChunk>, Self::Error> {
        teaql_data_service::StreamQueryExecutor::query_stream(&self.inner, request, chunk_size).await
    }
}

impl teaql_data_service::MutationExecutor for ServiceRuntimeExecutor {
    async fn mutate(&self, request: teaql_data_service::MutationRequest) -> Result<teaql_data_service::MutationResult, Self::Error> {
        teaql_data_service::MutationExecutor::mutate(&self.inner, request).await
    }
}

impl teaql_data_service::TransactionExecutor for ServiceRuntimeExecutor {
    type Tx<'a> = teaql_sql::SqlDataServiceTransaction<'a, DataServiceDialect, <DataServiceMutationExecutor as teaql_sql::SqlTransactionTransport>::Tx<'a>, LocalSchemaProvider> where Self: 'a;

    async fn begin(&self) -> Result<Self::Tx<'_ >, Self::Error> {
        teaql_data_service::TransactionExecutor::begin(&self.inner).await
    }
}

pub async fn service_runtime_from_env() -> Result<ServiceRuntime, ServiceRuntimeError> {
    service_runtime(ServiceRuntimeConfig::from_env()?).await
}

pub async fn service_runtime(config: ServiceRuntimeConfig) -> Result<ServiceRuntime, ServiceRuntimeError> {
    let pool = connect_data_service_pool(&config).await?;
    service_runtime_from_pool(pool).await
}

pub async fn service_runtime_from_pool(pool: DataServicePool) -> Result<ServiceRuntime, ServiceRuntimeError> {
    let mutation_executor = DataServiceMutationExecutor::new(pool);
    let id_generator = DataServiceIdGenerator::from_executor(mutation_executor.clone());let mut context = module_with_behaviors_and_checkers().into_context();
    context.set_internal_id_generator(id_generator);
    context.use_sqlite_provider(mutation_executor.clone());
    let executor = ServiceRuntimeExecutor::new(mutation_executor);
    context.register_executor(executor.clone());
    context.insert_resource(executor);

    // 自动加载 Zero-Code 审计配置与 Schema 模式
    let env_config = teaql_tool_core::audit_config_from_env(&[
        "company_data", "user_account_data", "role_definition_data", "user_role_data", "audit_log_data", "notification_rule_data", "document_storage_data", "employee_record_data", "payroll_calculation_data", "worked_hours_data", "bonus_record_data", "leave_request_data", "private_customer_data", "corporate_customer_data", "linked_contact_data", "billing_info_data", "interaction_history_data", "vehicle_asset_data", "equipment_item_data", "consumable_item_data", "maintenance_schedule_data", "inventory_tracking_data", "insurance_policy_data", "address_record_data", "move_order_data", "route_plan_data", "time_slot_data", "fulfillment_event_data", "job_assignment_data", "service_catalog_data", "service_config_data", "box_rental_data", "marketing_campaign_data", "discount_code_data", "lead_tracking_data", "conversion_metric_data", "invoice_document_data", "payment_record_data", "expense_record_data", "vat_record_data", "financial_summary_data", "service_contract_data"
    ]);
    let schema_mode = env_config.schema_mode;
    context.insert_resource(env_config.config.clone());
    context.insert_resource(env_config);

    match schema_mode {
        teaql_tool_core::SchemaMode::Execute => {
            context.ensure_schema().await?;
        }
        teaql_tool_core::SchemaMode::DryRun => {
            // DryRun: 目前等效于验证
            context.ensure_schema().await?;
        }
        teaql_tool_core::SchemaMode::Verify => {
            context.ensure_schema().await?;
        }
    }

    Ok(context)
}



fn env_value(name: &'static str) -> Result<String, ServiceRuntimeError> {
    std::env::var(name).map_err(|source| ServiceRuntimeError::MissingEnv { name, source })
}

async fn connect_data_service_pool(config: &ServiceRuntimeConfig) -> Result<DataServicePool, ServiceRuntimeError> {
    let url = &config.database_url;
    let sanitized_url = if url.starts_with("sqlite:") { url.strip_prefix("sqlite:").unwrap().trim_start_matches("//") } else { url };
    let pure_file_path = sanitized_url.split('?').next().unwrap_or(sanitized_url);
    let path = std::path::Path::new(pure_file_path);
    if let Some(parent) = path.parent() { if !parent.as_os_str().is_empty() { std::fs::create_dir_all(parent).map_err(|e| ServiceRuntimeError::ConnectionError(e.to_string()))?; } }
    Ok(std::sync::Arc::new(std::sync::Mutex::new(rusqlite::Connection::open(pure_file_path).map_err(|e| ServiceRuntimeError::ConnectionError(e.to_string()))?)))
}

pub fn repository_registry() -> teaql_runtime::InMemoryEntityRegistry {
    teaql_runtime::InMemoryEntityRegistry::new()
        .with_entity("Company")
        .with_entity("UserAccount")
        .with_entity("RoleDefinition")
        .with_entity("UserRole")
        .with_entity("AuditLog")
        .with_entity("NotificationRule")
        .with_entity("DocumentStorage")
        .with_entity("EmployeeRecord")
        .with_entity("PayrollCalculation")
        .with_entity("WorkedHours")
        .with_entity("BonusRecord")
        .with_entity("LeaveRequest")
        .with_entity("PrivateCustomer")
        .with_entity("CorporateCustomer")
        .with_entity("LinkedContact")
        .with_entity("BillingInfo")
        .with_entity("InteractionHistory")
        .with_entity("VehicleAsset")
        .with_entity("EquipmentItem")
        .with_entity("ConsumableItem")
        .with_entity("MaintenanceSchedule")
        .with_entity("InventoryTracking")
        .with_entity("InsurancePolicy")
        .with_entity("AddressRecord")
        .with_entity("MoveOrder")
        .with_entity("RoutePlan")
        .with_entity("TimeSlot")
        .with_entity("FulfillmentEvent")
        .with_entity("JobAssignment")
        .with_entity("ServiceCatalog")
        .with_entity("ServiceConfig")
        .with_entity("BoxRental")
        .with_entity("MarketingCampaign")
        .with_entity("DiscountCode")
        .with_entity("LeadTracking")
        .with_entity("ConversionMetric")
        .with_entity("InvoiceDocument")
        .with_entity("PaymentRecord")
        .with_entity("ExpenseRecord")
        .with_entity("VatRecord")
        .with_entity("FinancialSummary")
        .with_entity("ServiceContract")
}

pub fn behavior_registry() -> teaql_runtime::InMemoryEntityDataServiceBehaviorRegistry {
    teaql_runtime::InMemoryEntityDataServiceBehaviorRegistry::new()
        .with_behavior("Company", CompanyBehavior::default())
        .with_behavior("UserAccount", UserAccountBehavior::default())
        .with_behavior("RoleDefinition", RoleDefinitionBehavior::default())
        .with_behavior("UserRole", UserRoleBehavior::default())
        .with_behavior("AuditLog", AuditLogBehavior::default())
        .with_behavior("NotificationRule", NotificationRuleBehavior::default())
        .with_behavior("DocumentStorage", DocumentStorageBehavior::default())
        .with_behavior("EmployeeRecord", EmployeeRecordBehavior::default())
        .with_behavior("PayrollCalculation", PayrollCalculationBehavior::default())
        .with_behavior("WorkedHours", WorkedHoursBehavior::default())
        .with_behavior("BonusRecord", BonusRecordBehavior::default())
        .with_behavior("LeaveRequest", LeaveRequestBehavior::default())
        .with_behavior("PrivateCustomer", PrivateCustomerBehavior::default())
        .with_behavior("CorporateCustomer", CorporateCustomerBehavior::default())
        .with_behavior("LinkedContact", LinkedContactBehavior::default())
        .with_behavior("BillingInfo", BillingInfoBehavior::default())
        .with_behavior("InteractionHistory", InteractionHistoryBehavior::default())
        .with_behavior("VehicleAsset", VehicleAssetBehavior::default())
        .with_behavior("EquipmentItem", EquipmentItemBehavior::default())
        .with_behavior("ConsumableItem", ConsumableItemBehavior::default())
        .with_behavior("MaintenanceSchedule", MaintenanceScheduleBehavior::default())
        .with_behavior("InventoryTracking", InventoryTrackingBehavior::default())
        .with_behavior("InsurancePolicy", InsurancePolicyBehavior::default())
        .with_behavior("AddressRecord", AddressRecordBehavior::default())
        .with_behavior("MoveOrder", MoveOrderBehavior::default())
        .with_behavior("RoutePlan", RoutePlanBehavior::default())
        .with_behavior("TimeSlot", TimeSlotBehavior::default())
        .with_behavior("FulfillmentEvent", FulfillmentEventBehavior::default())
        .with_behavior("JobAssignment", JobAssignmentBehavior::default())
        .with_behavior("ServiceCatalog", ServiceCatalogBehavior::default())
        .with_behavior("ServiceConfig", ServiceConfigBehavior::default())
        .with_behavior("BoxRental", BoxRentalBehavior::default())
        .with_behavior("MarketingCampaign", MarketingCampaignBehavior::default())
        .with_behavior("DiscountCode", DiscountCodeBehavior::default())
        .with_behavior("LeadTracking", LeadTrackingBehavior::default())
        .with_behavior("ConversionMetric", ConversionMetricBehavior::default())
        .with_behavior("InvoiceDocument", InvoiceDocumentBehavior::default())
        .with_behavior("PaymentRecord", PaymentRecordBehavior::default())
        .with_behavior("ExpenseRecord", ExpenseRecordBehavior::default())
        .with_behavior("VatRecord", VatRecordBehavior::default())
        .with_behavior("FinancialSummary", FinancialSummaryBehavior::default())
        .with_behavior("ServiceContract", ServiceContractBehavior::default())
}

pub fn checker_registry() -> teaql_runtime::InMemoryCheckerRegistry {
    teaql_runtime::InMemoryCheckerRegistry::new()
        .with_checker(teaql_runtime::TypedEntityChecker::<Company, _>::new(CompanyChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<UserAccount, _>::new(UserAccountChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<RoleDefinition, _>::new(RoleDefinitionChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<UserRole, _>::new(UserRoleChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<AuditLog, _>::new(AuditLogChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<NotificationRule, _>::new(NotificationRuleChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<DocumentStorage, _>::new(DocumentStorageChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<EmployeeRecord, _>::new(EmployeeRecordChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<PayrollCalculation, _>::new(PayrollCalculationChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<WorkedHours, _>::new(WorkedHoursChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<BonusRecord, _>::new(BonusRecordChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<LeaveRequest, _>::new(LeaveRequestChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<PrivateCustomer, _>::new(PrivateCustomerChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<CorporateCustomer, _>::new(CorporateCustomerChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<LinkedContact, _>::new(LinkedContactChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<BillingInfo, _>::new(BillingInfoChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<InteractionHistory, _>::new(InteractionHistoryChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<VehicleAsset, _>::new(VehicleAssetChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<EquipmentItem, _>::new(EquipmentItemChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<ConsumableItem, _>::new(ConsumableItemChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<MaintenanceSchedule, _>::new(MaintenanceScheduleChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<InventoryTracking, _>::new(InventoryTrackingChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<InsurancePolicy, _>::new(InsurancePolicyChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<AddressRecord, _>::new(AddressRecordChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<MoveOrder, _>::new(MoveOrderChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<RoutePlan, _>::new(RoutePlanChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<TimeSlot, _>::new(TimeSlotChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<FulfillmentEvent, _>::new(FulfillmentEventChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<JobAssignment, _>::new(JobAssignmentChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<ServiceCatalog, _>::new(ServiceCatalogChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<ServiceConfig, _>::new(ServiceConfigChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<BoxRental, _>::new(BoxRentalChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<MarketingCampaign, _>::new(MarketingCampaignChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<DiscountCode, _>::new(DiscountCodeChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<LeadTracking, _>::new(LeadTrackingChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<ConversionMetric, _>::new(ConversionMetricChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<InvoiceDocument, _>::new(InvoiceDocumentChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<PaymentRecord, _>::new(PaymentRecordChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<ExpenseRecord, _>::new(ExpenseRecordChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<VatRecord, _>::new(VatRecordChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<FinancialSummary, _>::new(FinancialSummaryChecker::default()))
        .with_checker(teaql_runtime::TypedEntityChecker::<ServiceContract, _>::new(ServiceContractChecker::default()))
}

pub fn module() -> teaql_runtime::RuntimeModule {
    teaql_runtime::RuntimeModule::new()
        .entity::<Company>()
        .entity::<UserAccount>()
        .entity::<RoleDefinition>()
        .entity::<UserRole>()
        .entity::<AuditLog>()
        .entity::<NotificationRule>()
        .entity::<DocumentStorage>()
        .entity::<EmployeeRecord>()
        .entity::<PayrollCalculation>()
        .entity::<WorkedHours>()
        .entity::<BonusRecord>()
        .entity::<LeaveRequest>()
        .entity::<PrivateCustomer>()
        .entity::<CorporateCustomer>()
        .entity::<LinkedContact>()
        .entity::<BillingInfo>()
        .entity::<InteractionHistory>()
        .entity::<VehicleAsset>()
        .entity::<EquipmentItem>()
        .entity::<ConsumableItem>()
        .entity::<MaintenanceSchedule>()
        .entity::<InventoryTracking>()
        .entity::<InsurancePolicy>()
        .entity::<AddressRecord>()
        .entity::<MoveOrder>()
        .entity::<RoutePlan>()
        .entity::<TimeSlot>()
        .entity::<FulfillmentEvent>()
        .entity::<JobAssignment>()
        .entity::<ServiceCatalog>()
        .entity::<ServiceConfig>()
        .entity::<BoxRental>()
        .entity::<MarketingCampaign>()
        .entity::<DiscountCode>()
        .entity::<LeadTracking>()
        .entity::<ConversionMetric>()
        .entity::<InvoiceDocument>()
        .entity::<PaymentRecord>()
        .entity::<ExpenseRecord>()
        .entity::<VatRecord>()
        .entity::<FinancialSummary>()
        .entity::<ServiceContract>()
        .initial_graph(teaql_runtime::GraphNode::new("Company")
            .value("id", 1_u64)
            .value("company_name", "Fast Movers Inc")
            .value("founded_year", 1998_i64)
            .value("create_time", chrono::Utc::now())
            .value("update_time", chrono::Utc::now())
            .value("version", 1_i64))
}

pub fn module_with_checkers() -> teaql_runtime::RuntimeModule {
    teaql_runtime::RuntimeModule::new()
        .entity::<Company>()
        .checker(teaql_runtime::TypedEntityChecker::<Company, _>::new(CompanyChecker::default()))
        .entity::<UserAccount>()
        .checker(teaql_runtime::TypedEntityChecker::<UserAccount, _>::new(UserAccountChecker::default()))
        .entity::<RoleDefinition>()
        .checker(teaql_runtime::TypedEntityChecker::<RoleDefinition, _>::new(RoleDefinitionChecker::default()))
        .entity::<UserRole>()
        .checker(teaql_runtime::TypedEntityChecker::<UserRole, _>::new(UserRoleChecker::default()))
        .entity::<AuditLog>()
        .checker(teaql_runtime::TypedEntityChecker::<AuditLog, _>::new(AuditLogChecker::default()))
        .entity::<NotificationRule>()
        .checker(teaql_runtime::TypedEntityChecker::<NotificationRule, _>::new(NotificationRuleChecker::default()))
        .entity::<DocumentStorage>()
        .checker(teaql_runtime::TypedEntityChecker::<DocumentStorage, _>::new(DocumentStorageChecker::default()))
        .entity::<EmployeeRecord>()
        .checker(teaql_runtime::TypedEntityChecker::<EmployeeRecord, _>::new(EmployeeRecordChecker::default()))
        .entity::<PayrollCalculation>()
        .checker(teaql_runtime::TypedEntityChecker::<PayrollCalculation, _>::new(PayrollCalculationChecker::default()))
        .entity::<WorkedHours>()
        .checker(teaql_runtime::TypedEntityChecker::<WorkedHours, _>::new(WorkedHoursChecker::default()))
        .entity::<BonusRecord>()
        .checker(teaql_runtime::TypedEntityChecker::<BonusRecord, _>::new(BonusRecordChecker::default()))
        .entity::<LeaveRequest>()
        .checker(teaql_runtime::TypedEntityChecker::<LeaveRequest, _>::new(LeaveRequestChecker::default()))
        .entity::<PrivateCustomer>()
        .checker(teaql_runtime::TypedEntityChecker::<PrivateCustomer, _>::new(PrivateCustomerChecker::default()))
        .entity::<CorporateCustomer>()
        .checker(teaql_runtime::TypedEntityChecker::<CorporateCustomer, _>::new(CorporateCustomerChecker::default()))
        .entity::<LinkedContact>()
        .checker(teaql_runtime::TypedEntityChecker::<LinkedContact, _>::new(LinkedContactChecker::default()))
        .entity::<BillingInfo>()
        .checker(teaql_runtime::TypedEntityChecker::<BillingInfo, _>::new(BillingInfoChecker::default()))
        .entity::<InteractionHistory>()
        .checker(teaql_runtime::TypedEntityChecker::<InteractionHistory, _>::new(InteractionHistoryChecker::default()))
        .entity::<VehicleAsset>()
        .checker(teaql_runtime::TypedEntityChecker::<VehicleAsset, _>::new(VehicleAssetChecker::default()))
        .entity::<EquipmentItem>()
        .checker(teaql_runtime::TypedEntityChecker::<EquipmentItem, _>::new(EquipmentItemChecker::default()))
        .entity::<ConsumableItem>()
        .checker(teaql_runtime::TypedEntityChecker::<ConsumableItem, _>::new(ConsumableItemChecker::default()))
        .entity::<MaintenanceSchedule>()
        .checker(teaql_runtime::TypedEntityChecker::<MaintenanceSchedule, _>::new(MaintenanceScheduleChecker::default()))
        .entity::<InventoryTracking>()
        .checker(teaql_runtime::TypedEntityChecker::<InventoryTracking, _>::new(InventoryTrackingChecker::default()))
        .entity::<InsurancePolicy>()
        .checker(teaql_runtime::TypedEntityChecker::<InsurancePolicy, _>::new(InsurancePolicyChecker::default()))
        .entity::<AddressRecord>()
        .checker(teaql_runtime::TypedEntityChecker::<AddressRecord, _>::new(AddressRecordChecker::default()))
        .entity::<MoveOrder>()
        .checker(teaql_runtime::TypedEntityChecker::<MoveOrder, _>::new(MoveOrderChecker::default()))
        .entity::<RoutePlan>()
        .checker(teaql_runtime::TypedEntityChecker::<RoutePlan, _>::new(RoutePlanChecker::default()))
        .entity::<TimeSlot>()
        .checker(teaql_runtime::TypedEntityChecker::<TimeSlot, _>::new(TimeSlotChecker::default()))
        .entity::<FulfillmentEvent>()
        .checker(teaql_runtime::TypedEntityChecker::<FulfillmentEvent, _>::new(FulfillmentEventChecker::default()))
        .entity::<JobAssignment>()
        .checker(teaql_runtime::TypedEntityChecker::<JobAssignment, _>::new(JobAssignmentChecker::default()))
        .entity::<ServiceCatalog>()
        .checker(teaql_runtime::TypedEntityChecker::<ServiceCatalog, _>::new(ServiceCatalogChecker::default()))
        .entity::<ServiceConfig>()
        .checker(teaql_runtime::TypedEntityChecker::<ServiceConfig, _>::new(ServiceConfigChecker::default()))
        .entity::<BoxRental>()
        .checker(teaql_runtime::TypedEntityChecker::<BoxRental, _>::new(BoxRentalChecker::default()))
        .entity::<MarketingCampaign>()
        .checker(teaql_runtime::TypedEntityChecker::<MarketingCampaign, _>::new(MarketingCampaignChecker::default()))
        .entity::<DiscountCode>()
        .checker(teaql_runtime::TypedEntityChecker::<DiscountCode, _>::new(DiscountCodeChecker::default()))
        .entity::<LeadTracking>()
        .checker(teaql_runtime::TypedEntityChecker::<LeadTracking, _>::new(LeadTrackingChecker::default()))
        .entity::<ConversionMetric>()
        .checker(teaql_runtime::TypedEntityChecker::<ConversionMetric, _>::new(ConversionMetricChecker::default()))
        .entity::<InvoiceDocument>()
        .checker(teaql_runtime::TypedEntityChecker::<InvoiceDocument, _>::new(InvoiceDocumentChecker::default()))
        .entity::<PaymentRecord>()
        .checker(teaql_runtime::TypedEntityChecker::<PaymentRecord, _>::new(PaymentRecordChecker::default()))
        .entity::<ExpenseRecord>()
        .checker(teaql_runtime::TypedEntityChecker::<ExpenseRecord, _>::new(ExpenseRecordChecker::default()))
        .entity::<VatRecord>()
        .checker(teaql_runtime::TypedEntityChecker::<VatRecord, _>::new(VatRecordChecker::default()))
        .entity::<FinancialSummary>()
        .checker(teaql_runtime::TypedEntityChecker::<FinancialSummary, _>::new(FinancialSummaryChecker::default()))
        .entity::<ServiceContract>()
        .checker(teaql_runtime::TypedEntityChecker::<ServiceContract, _>::new(ServiceContractChecker::default()))
        .initial_graph(teaql_runtime::GraphNode::new("Company")
            .value("id", 1_u64)
            .value("company_name", "Fast Movers Inc")
            .value("founded_year", 1998_i64)
            .value("create_time", chrono::Utc::now())
            .value("update_time", chrono::Utc::now())
            .value("version", 1_i64))
}

pub fn module_with_behaviors() -> teaql_runtime::RuntimeModule {
    teaql_runtime::RuntimeModule::new()
        .entity_with_behavior::<Company, _>(CompanyBehavior::default())
        .entity_with_behavior::<UserAccount, _>(UserAccountBehavior::default())
        .entity_with_behavior::<RoleDefinition, _>(RoleDefinitionBehavior::default())
        .entity_with_behavior::<UserRole, _>(UserRoleBehavior::default())
        .entity_with_behavior::<AuditLog, _>(AuditLogBehavior::default())
        .entity_with_behavior::<NotificationRule, _>(NotificationRuleBehavior::default())
        .entity_with_behavior::<DocumentStorage, _>(DocumentStorageBehavior::default())
        .entity_with_behavior::<EmployeeRecord, _>(EmployeeRecordBehavior::default())
        .entity_with_behavior::<PayrollCalculation, _>(PayrollCalculationBehavior::default())
        .entity_with_behavior::<WorkedHours, _>(WorkedHoursBehavior::default())
        .entity_with_behavior::<BonusRecord, _>(BonusRecordBehavior::default())
        .entity_with_behavior::<LeaveRequest, _>(LeaveRequestBehavior::default())
        .entity_with_behavior::<PrivateCustomer, _>(PrivateCustomerBehavior::default())
        .entity_with_behavior::<CorporateCustomer, _>(CorporateCustomerBehavior::default())
        .entity_with_behavior::<LinkedContact, _>(LinkedContactBehavior::default())
        .entity_with_behavior::<BillingInfo, _>(BillingInfoBehavior::default())
        .entity_with_behavior::<InteractionHistory, _>(InteractionHistoryBehavior::default())
        .entity_with_behavior::<VehicleAsset, _>(VehicleAssetBehavior::default())
        .entity_with_behavior::<EquipmentItem, _>(EquipmentItemBehavior::default())
        .entity_with_behavior::<ConsumableItem, _>(ConsumableItemBehavior::default())
        .entity_with_behavior::<MaintenanceSchedule, _>(MaintenanceScheduleBehavior::default())
        .entity_with_behavior::<InventoryTracking, _>(InventoryTrackingBehavior::default())
        .entity_with_behavior::<InsurancePolicy, _>(InsurancePolicyBehavior::default())
        .entity_with_behavior::<AddressRecord, _>(AddressRecordBehavior::default())
        .entity_with_behavior::<MoveOrder, _>(MoveOrderBehavior::default())
        .entity_with_behavior::<RoutePlan, _>(RoutePlanBehavior::default())
        .entity_with_behavior::<TimeSlot, _>(TimeSlotBehavior::default())
        .entity_with_behavior::<FulfillmentEvent, _>(FulfillmentEventBehavior::default())
        .entity_with_behavior::<JobAssignment, _>(JobAssignmentBehavior::default())
        .entity_with_behavior::<ServiceCatalog, _>(ServiceCatalogBehavior::default())
        .entity_with_behavior::<ServiceConfig, _>(ServiceConfigBehavior::default())
        .entity_with_behavior::<BoxRental, _>(BoxRentalBehavior::default())
        .entity_with_behavior::<MarketingCampaign, _>(MarketingCampaignBehavior::default())
        .entity_with_behavior::<DiscountCode, _>(DiscountCodeBehavior::default())
        .entity_with_behavior::<LeadTracking, _>(LeadTrackingBehavior::default())
        .entity_with_behavior::<ConversionMetric, _>(ConversionMetricBehavior::default())
        .entity_with_behavior::<InvoiceDocument, _>(InvoiceDocumentBehavior::default())
        .entity_with_behavior::<PaymentRecord, _>(PaymentRecordBehavior::default())
        .entity_with_behavior::<ExpenseRecord, _>(ExpenseRecordBehavior::default())
        .entity_with_behavior::<VatRecord, _>(VatRecordBehavior::default())
        .entity_with_behavior::<FinancialSummary, _>(FinancialSummaryBehavior::default())
        .entity_with_behavior::<ServiceContract, _>(ServiceContractBehavior::default())
        .initial_graph(teaql_runtime::GraphNode::new("Company")
            .value("id", 1_u64)
            .value("company_name", "Fast Movers Inc")
            .value("founded_year", 1998_i64)
            .value("create_time", chrono::Utc::now())
            .value("update_time", chrono::Utc::now())
            .value("version", 1_i64))
}

pub fn module_with_behaviors_and_checkers() -> teaql_runtime::RuntimeModule {
    teaql_runtime::RuntimeModule::new()
        .entity_with_behavior::<Company, _>(CompanyBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<Company, _>::new(CompanyChecker::default()))
        .entity_with_behavior::<UserAccount, _>(UserAccountBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<UserAccount, _>::new(UserAccountChecker::default()))
        .entity_with_behavior::<RoleDefinition, _>(RoleDefinitionBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<RoleDefinition, _>::new(RoleDefinitionChecker::default()))
        .entity_with_behavior::<UserRole, _>(UserRoleBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<UserRole, _>::new(UserRoleChecker::default()))
        .entity_with_behavior::<AuditLog, _>(AuditLogBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<AuditLog, _>::new(AuditLogChecker::default()))
        .entity_with_behavior::<NotificationRule, _>(NotificationRuleBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<NotificationRule, _>::new(NotificationRuleChecker::default()))
        .entity_with_behavior::<DocumentStorage, _>(DocumentStorageBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<DocumentStorage, _>::new(DocumentStorageChecker::default()))
        .entity_with_behavior::<EmployeeRecord, _>(EmployeeRecordBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<EmployeeRecord, _>::new(EmployeeRecordChecker::default()))
        .entity_with_behavior::<PayrollCalculation, _>(PayrollCalculationBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<PayrollCalculation, _>::new(PayrollCalculationChecker::default()))
        .entity_with_behavior::<WorkedHours, _>(WorkedHoursBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<WorkedHours, _>::new(WorkedHoursChecker::default()))
        .entity_with_behavior::<BonusRecord, _>(BonusRecordBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<BonusRecord, _>::new(BonusRecordChecker::default()))
        .entity_with_behavior::<LeaveRequest, _>(LeaveRequestBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<LeaveRequest, _>::new(LeaveRequestChecker::default()))
        .entity_with_behavior::<PrivateCustomer, _>(PrivateCustomerBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<PrivateCustomer, _>::new(PrivateCustomerChecker::default()))
        .entity_with_behavior::<CorporateCustomer, _>(CorporateCustomerBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<CorporateCustomer, _>::new(CorporateCustomerChecker::default()))
        .entity_with_behavior::<LinkedContact, _>(LinkedContactBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<LinkedContact, _>::new(LinkedContactChecker::default()))
        .entity_with_behavior::<BillingInfo, _>(BillingInfoBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<BillingInfo, _>::new(BillingInfoChecker::default()))
        .entity_with_behavior::<InteractionHistory, _>(InteractionHistoryBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<InteractionHistory, _>::new(InteractionHistoryChecker::default()))
        .entity_with_behavior::<VehicleAsset, _>(VehicleAssetBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<VehicleAsset, _>::new(VehicleAssetChecker::default()))
        .entity_with_behavior::<EquipmentItem, _>(EquipmentItemBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<EquipmentItem, _>::new(EquipmentItemChecker::default()))
        .entity_with_behavior::<ConsumableItem, _>(ConsumableItemBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<ConsumableItem, _>::new(ConsumableItemChecker::default()))
        .entity_with_behavior::<MaintenanceSchedule, _>(MaintenanceScheduleBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<MaintenanceSchedule, _>::new(MaintenanceScheduleChecker::default()))
        .entity_with_behavior::<InventoryTracking, _>(InventoryTrackingBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<InventoryTracking, _>::new(InventoryTrackingChecker::default()))
        .entity_with_behavior::<InsurancePolicy, _>(InsurancePolicyBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<InsurancePolicy, _>::new(InsurancePolicyChecker::default()))
        .entity_with_behavior::<AddressRecord, _>(AddressRecordBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<AddressRecord, _>::new(AddressRecordChecker::default()))
        .entity_with_behavior::<MoveOrder, _>(MoveOrderBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<MoveOrder, _>::new(MoveOrderChecker::default()))
        .entity_with_behavior::<RoutePlan, _>(RoutePlanBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<RoutePlan, _>::new(RoutePlanChecker::default()))
        .entity_with_behavior::<TimeSlot, _>(TimeSlotBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<TimeSlot, _>::new(TimeSlotChecker::default()))
        .entity_with_behavior::<FulfillmentEvent, _>(FulfillmentEventBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<FulfillmentEvent, _>::new(FulfillmentEventChecker::default()))
        .entity_with_behavior::<JobAssignment, _>(JobAssignmentBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<JobAssignment, _>::new(JobAssignmentChecker::default()))
        .entity_with_behavior::<ServiceCatalog, _>(ServiceCatalogBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<ServiceCatalog, _>::new(ServiceCatalogChecker::default()))
        .entity_with_behavior::<ServiceConfig, _>(ServiceConfigBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<ServiceConfig, _>::new(ServiceConfigChecker::default()))
        .entity_with_behavior::<BoxRental, _>(BoxRentalBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<BoxRental, _>::new(BoxRentalChecker::default()))
        .entity_with_behavior::<MarketingCampaign, _>(MarketingCampaignBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<MarketingCampaign, _>::new(MarketingCampaignChecker::default()))
        .entity_with_behavior::<DiscountCode, _>(DiscountCodeBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<DiscountCode, _>::new(DiscountCodeChecker::default()))
        .entity_with_behavior::<LeadTracking, _>(LeadTrackingBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<LeadTracking, _>::new(LeadTrackingChecker::default()))
        .entity_with_behavior::<ConversionMetric, _>(ConversionMetricBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<ConversionMetric, _>::new(ConversionMetricChecker::default()))
        .entity_with_behavior::<InvoiceDocument, _>(InvoiceDocumentBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<InvoiceDocument, _>::new(InvoiceDocumentChecker::default()))
        .entity_with_behavior::<PaymentRecord, _>(PaymentRecordBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<PaymentRecord, _>::new(PaymentRecordChecker::default()))
        .entity_with_behavior::<ExpenseRecord, _>(ExpenseRecordBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<ExpenseRecord, _>::new(ExpenseRecordChecker::default()))
        .entity_with_behavior::<VatRecord, _>(VatRecordBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<VatRecord, _>::new(VatRecordChecker::default()))
        .entity_with_behavior::<FinancialSummary, _>(FinancialSummaryBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<FinancialSummary, _>::new(FinancialSummaryChecker::default()))
        .entity_with_behavior::<ServiceContract, _>(ServiceContractBehavior::default())
        .checker(teaql_runtime::TypedEntityChecker::<ServiceContract, _>::new(ServiceContractChecker::default()))
        .initial_graph(teaql_runtime::GraphNode::new("Company")
            .value("id", 1_u64)
            .value("company_name", "Fast Movers Inc")
            .value("founded_year", 1998_i64)
            .value("create_time", chrono::Utc::now())
            .value("update_time", chrono::Utc::now())
            .value("version", 1_i64))
}