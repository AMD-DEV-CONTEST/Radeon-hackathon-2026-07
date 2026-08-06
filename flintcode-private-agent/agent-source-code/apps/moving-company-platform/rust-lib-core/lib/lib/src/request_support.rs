
#![allow(unused_imports)]
#![allow(async_fn_in_trait)]
use std::{collections::BTreeMap, future::Future, marker::PhantomData};

use serde_json::Value as JsonValue;
use teaql_core::{
    BinaryOp, Expr, Record,
    RelationAggregate as RuntimeRelationAggregate, SelectQuery, SmartList,
};
use teaql_runtime::{ContextError, GraphNode, EntityDataServiceBehavior, DataServiceError, PurposedSelectQuery, RuntimeError, UserContext};

// Re-export query builder types from teaql_core::request
pub use teaql_core::request::{
    COUNT_ALIAS, TYPE_FIELD, TYPE_GROUP_FIELD,
    FieldOperator, DateRange, EntityReference,
    QuerySelection, RelationSelection, RelationFilter, QueryOptions,
    UnsafeRawSqlSegment, RawDynamicProperty, RawProjection,
    RelationAggregate, FacetRequest, ObjectGroupBy,
    apply_relation_selections, apply_runtime_metadata,
    field_operator_expr, field_operator_column_expr,
    required_value, required_text,
    remove_default_live_filter, remove_filter_expr,
    dynamic_json_value_to_teaql_value, dynamic_json_values,
    dynamic_json_operator, dynamic_json_filter_expr,
    dynamic_json_u64_field,
    runtime_relation_aggregates,
    merge_outer_filter_into_facet_aggregates, attach_facets,
};


pub trait TeaqlRecordRepository {
    type Error: std::error::Error + Send + Sync + 'static;

    async fn fetch_all(&self, query: &PurposedSelectQuery) -> Result<Vec<Record>, DataServiceError<Self::Error>>;

    async fn fetch_smart_list(&self, query: &PurposedSelectQuery) -> Result<SmartList<Record>, DataServiceError<Self::Error>>;

    async fn fetch_smart_list_with_relation_aggregates(
        &self,
        query: &PurposedSelectQuery,
        relation_aggregates: &[RuntimeRelationAggregate],
    ) -> Result<SmartList<Record>, DataServiceError<Self::Error>>;

    async fn fetch_stream(&self, query: &PurposedSelectQuery) -> Result<Vec<teaql_data_service::StreamChunk>, DataServiceError<Self::Error>>;
}

pub trait TeaqlEntityRepository: TeaqlRecordRepository {
    async fn fetch_enhanced_entities<T>(&self, query: &PurposedSelectQuery) -> Result<SmartList<T>, DataServiceError<Self::Error>>
    where
        T: teaql_core::Entity;

    async fn fetch_enhanced_entities_with_relation_aggregates<T>(
        &self,
        query: &PurposedSelectQuery,
        relation_aggregates: &[RuntimeRelationAggregate],
    ) -> Result<SmartList<T>, DataServiceError<Self::Error>>
    where
        T: teaql_core::Entity;

}

impl<'a, E> TeaqlRecordRepository for teaql_runtime::EntityDataService<'a, E>
where
    E: teaql_data_service::QueryExecutor + teaql_data_service::MutationExecutor + teaql_data_service::StreamQueryExecutor + Send + Sync + 'static,
{
    type Error = E::Error;

    async fn fetch_all(&self, query: &PurposedSelectQuery) -> Result<Vec<Record>, DataServiceError<Self::Error>> {
        teaql_runtime::EntityDataService::fetch_all(self, query).await
    }

    async fn fetch_smart_list(&self, query: &PurposedSelectQuery) -> Result<SmartList<Record>, DataServiceError<Self::Error>> {
        teaql_runtime::EntityDataService::fetch_smart_list(self, query).await
    }

    async fn fetch_smart_list_with_relation_aggregates(
        &self,
        query: &PurposedSelectQuery,
        relation_aggregates: &[RuntimeRelationAggregate],
    ) -> Result<SmartList<Record>, DataServiceError<Self::Error>> {
        teaql_runtime::EntityDataService::fetch_smart_list_with_relation_aggregates(
            self,
            query,
            relation_aggregates,
        ).await
    }

    async fn fetch_stream(&self, query: &PurposedSelectQuery) -> Result<Vec<teaql_data_service::StreamChunk>, DataServiceError<Self::Error>> {
        teaql_runtime::EntityDataService::fetch_stream(self, query).await
    }
}

impl<'a, E> TeaqlEntityRepository for teaql_runtime::EntityDataService<'a, E>
where
    E: teaql_data_service::QueryExecutor + teaql_data_service::MutationExecutor + teaql_data_service::StreamQueryExecutor + Send + Sync + 'static,
{
    async fn fetch_enhanced_entities<T>(&self, query: &PurposedSelectQuery) -> Result<SmartList<T>, DataServiceError<Self::Error>>
    where
        T: teaql_core::Entity,
    {
        teaql_runtime::EntityDataService::fetch_enhanced_entities(self, query).await
    }

    async fn fetch_enhanced_entities_with_relation_aggregates<T>(
        &self,
        query: &PurposedSelectQuery,
        relation_aggregates: &[RuntimeRelationAggregate],
    ) -> Result<SmartList<T>, DataServiceError<Self::Error>>
    where
        T: teaql_core::Entity,
    {
        teaql_runtime::EntityDataService::fetch_enhanced_entities_with_relation_aggregates(
            self,
            query,
            relation_aggregates,
        ).await
    }

}

pub type TeaqlDataServiceError<R> = DataServiceError<<R as TeaqlRecordRepository>::Error>;

pub(crate) fn authorize_query(mut query: SelectQuery) -> Result<PurposedSelectQuery, RuntimeError> {
    let purpose = query
        .trace_chain
        .pop()
        .map(|node| node.comment)
        .filter(|purpose| !purpose.trim().is_empty())
        .ok_or_else(|| RuntimeError::Graph(
            "generated query reached the repository without .purpose(...)".to_owned()
        ))?;
    Ok(PurposedSelectQuery::new(query, purpose))
}

pub trait TeaqlRuntime {
    fn user_context(&self) -> &UserContext;

    fn fetch_facet_smart_list(
        &self,
        entity: &str,
        query: &PurposedSelectQuery,
        relation_aggregates: &[RuntimeRelationAggregate],
        trace_context: Vec<teaql_core::TraceNode>,
    ) -> impl std::future::Future<Output = Result<SmartList<Record>, RuntimeError>> + Send;
}

/// Internal trait for repository access. Application code should not use this trait directly.
#[doc(hidden)]
pub trait AuditedSave<'a, C>
where
    C: TeaqlRepositoryProvider + ?Sized + 'a,
{
    type Error;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>>;
}



pub trait TeaqlRepositoryProvider: TeaqlRuntime {
    type MoveStatusRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn move_status_repository(&self) -> Result<Self::MoveStatusRepository<'_>, ContextError>;
    type CompanyProfileRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn company_profile_repository(&self) -> Result<Self::CompanyProfileRepository<'_>, ContextError>;
    type LocationAddressRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn location_address_repository(&self) -> Result<Self::LocationAddressRepository<'_>, ContextError>;
    type MoveOrderRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn move_order_repository(&self) -> Result<Self::MoveOrderRepository<'_>, ContextError>;
    type RoutePlanRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn route_plan_repository(&self) -> Result<Self::RoutePlanRepository<'_>, ContextError>;
    type FulfillmentEventRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn fulfillment_event_repository(&self) -> Result<Self::FulfillmentEventRepository<'_>, ContextError>;
    type JobTitleRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn job_title_repository(&self) -> Result<Self::JobTitleRepository<'_>, ContextError>;
    type EmployeeRegistryRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn employee_registry_repository(&self) -> Result<Self::EmployeeRegistryRepository<'_>, ContextError>;
    type JobAssignmentRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn job_assignment_repository(&self) -> Result<Self::JobAssignmentRepository<'_>, ContextError>;
    type WorkedHoursRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn worked_hours_repository(&self) -> Result<Self::WorkedHoursRepository<'_>, ContextError>;
    type PayrollCalculationRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn payroll_calculation_repository(&self) -> Result<Self::PayrollCalculationRepository<'_>, ContextError>;
    type ShiftScheduleRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn shift_schedule_repository(&self) -> Result<Self::ShiftScheduleRepository<'_>, ContextError>;
    type CustomerTypeRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn customer_type_repository(&self) -> Result<Self::CustomerTypeRepository<'_>, ContextError>;
    type CustomerProfileRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn customer_profile_repository(&self) -> Result<Self::CustomerProfileRepository<'_>, ContextError>;
    type ContactPersonRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn contact_person_repository(&self) -> Result<Self::ContactPersonRepository<'_>, ContextError>;
    type CustomerFeedbackRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn customer_feedback_repository(&self) -> Result<Self::CustomerFeedbackRepository<'_>, ContextError>;
    type LoyaltyProgramRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn loyalty_program_repository(&self) -> Result<Self::LoyaltyProgramRepository<'_>, ContextError>;
    type ServiceCategoryRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn service_category_repository(&self) -> Result<Self::ServiceCategoryRepository<'_>, ContextError>;
    type ServiceCatalogRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn service_catalog_repository(&self) -> Result<Self::ServiceCatalogRepository<'_>, ContextError>;
    type BoxRentalRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn box_rental_repository(&self) -> Result<Self::BoxRentalRepository<'_>, ContextError>;
    type ServiceBundleRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn service_bundle_repository(&self) -> Result<Self::ServiceBundleRepository<'_>, ContextError>;
    type CampaignStatusRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn campaign_status_repository(&self) -> Result<Self::CampaignStatusRepository<'_>, ContextError>;
    type MarketingCampaignRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn marketing_campaign_repository(&self) -> Result<Self::MarketingCampaignRepository<'_>, ContextError>;
    type SalesLeadRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn sales_lead_repository(&self) -> Result<Self::SalesLeadRepository<'_>, ContextError>;
    type PaymentMethodRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn payment_method_repository(&self) -> Result<Self::PaymentMethodRepository<'_>, ContextError>;
    type InvoiceDocumentRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn invoice_document_repository(&self) -> Result<Self::InvoiceDocumentRepository<'_>, ContextError>;
    type PaymentRecordRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn payment_record_repository(&self) -> Result<Self::PaymentRecordRepository<'_>, ContextError>;
    type ExpenseRecordRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn expense_record_repository(&self) -> Result<Self::ExpenseRecordRepository<'_>, ContextError>;
    type VehicleTypeRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn vehicle_type_repository(&self) -> Result<Self::VehicleTypeRepository<'_>, ContextError>;
    type FleetVehicleRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn fleet_vehicle_repository(&self) -> Result<Self::FleetVehicleRepository<'_>, ContextError>;
    type EquipmentItemRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn equipment_item_repository(&self) -> Result<Self::EquipmentItemRepository<'_>, ContextError>;
    type MaintenanceScheduleRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn maintenance_schedule_repository(&self) -> Result<Self::MaintenanceScheduleRepository<'_>, ContextError>;
    type FuelLogRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn fuel_log_repository(&self) -> Result<Self::FuelLogRepository<'_>, ContextError>;
    type UserRoleRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn user_role_repository(&self) -> Result<Self::UserRoleRepository<'_>, ContextError>;
    type NotificationTypeRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn notification_type_repository(&self) -> Result<Self::NotificationTypeRepository<'_>, ContextError>;
    type UserAccountRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn user_account_repository(&self) -> Result<Self::UserAccountRepository<'_>, ContextError>;
    type RoleDefinitionRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn role_definition_repository(&self) -> Result<Self::RoleDefinitionRepository<'_>, ContextError>;
    type RoleAssignmentRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn role_assignment_repository(&self) -> Result<Self::RoleAssignmentRepository<'_>, ContextError>;
    type AuditLogRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn audit_log_repository(&self) -> Result<Self::AuditLogRepository<'_>, ContextError>;
    type ServiceContractRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn service_contract_repository(&self) -> Result<Self::ServiceContractRepository<'_>, ContextError>;
}

#[allow(async_fn_in_trait)]
pub trait TeaqlUserContextExt {
    async fn transaction_data<F, Fut>(&self, f: F) -> Result<(), DataServiceError<<crate::runtime::DataServiceExecutor as teaql_data_service::DataServiceExecutor>::Error>>
    where
        F: FnOnce() -> Fut,
        Fut: Future<Output = Result<(), DataServiceError<<crate::runtime::DataServiceExecutor as teaql_data_service::DataServiceExecutor>::Error>>>;
}

impl TeaqlUserContextExt for teaql_runtime::UserContext {
    async fn transaction_data<F, Fut>(&self, f: F) -> Result<(), DataServiceError<<crate::runtime::DataServiceExecutor as teaql_data_service::DataServiceExecutor>::Error>>
    where
        F: FnOnce() -> Fut,
        Fut: Future<Output = Result<(), DataServiceError<<crate::runtime::DataServiceExecutor as teaql_data_service::DataServiceExecutor>::Error>>>,
    {
        let executor = self.require_resource::<crate::runtime::DataServiceExecutor>().map_err(|err| {
            DataServiceError::Runtime(RuntimeError::Graph(format!(
                "cannot start transaction without executor: {err}"
            )))
        })?;
        let root = self.entity_root();

        let tx = teaql_data_service::TransactionExecutor::begin(&*executor).await.map_err(DataServiceError::Executor)?;
        root.push_change_set();

        let result = f().await;
        match result {
            Ok(()) => {
                root.pop_change_set();
                teaql_data_service::Transaction::commit(tx).await.map_err(DataServiceError::Executor)?;
                Ok(())
            }
            Err(err) => {
                root.pop_change_set();
                teaql_data_service::Transaction::rollback(tx).await.map_err(DataServiceError::Executor)?;
                Err(err)
            }
        }
    }
}

impl TeaqlRuntime for teaql_runtime::UserContext {
    fn user_context(&self) -> &UserContext {
        self
    }

    async fn fetch_facet_smart_list(
        &self,
        entity: &str,
        query: &PurposedSelectQuery,
        relation_aggregates: &[RuntimeRelationAggregate],
        trace_context: Vec<teaql_core::TraceNode>,
    ) -> Result<SmartList<Record>, RuntimeError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>(entity)
            .map_err(|err| RuntimeError::Graph(err.to_string()))?
            .with_trace_context(trace_context)
            .fetch_smart_list_with_relation_aggregates(query, relation_aggregates)
            .await
            .map_err(|err| RuntimeError::Graph(err.to_string()))
    }
}

impl TeaqlRepositoryProvider for teaql_runtime::UserContext {
    type MoveStatusRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn move_status_repository(&self) -> Result<Self::MoveStatusRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("MoveStatus")
    }

    type CompanyProfileRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn company_profile_repository(&self) -> Result<Self::CompanyProfileRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("CompanyProfile")
    }

    type LocationAddressRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn location_address_repository(&self) -> Result<Self::LocationAddressRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("LocationAddress")
    }

    type MoveOrderRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn move_order_repository(&self) -> Result<Self::MoveOrderRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("MoveOrder")
    }

    type RoutePlanRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn route_plan_repository(&self) -> Result<Self::RoutePlanRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("RoutePlan")
    }

    type FulfillmentEventRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn fulfillment_event_repository(&self) -> Result<Self::FulfillmentEventRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("FulfillmentEvent")
    }

    type JobTitleRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn job_title_repository(&self) -> Result<Self::JobTitleRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("JobTitle")
    }

    type EmployeeRegistryRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn employee_registry_repository(&self) -> Result<Self::EmployeeRegistryRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("EmployeeRegistry")
    }

    type JobAssignmentRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn job_assignment_repository(&self) -> Result<Self::JobAssignmentRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("JobAssignment")
    }

    type WorkedHoursRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn worked_hours_repository(&self) -> Result<Self::WorkedHoursRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("WorkedHours")
    }

    type PayrollCalculationRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn payroll_calculation_repository(&self) -> Result<Self::PayrollCalculationRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("PayrollCalculation")
    }

    type ShiftScheduleRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn shift_schedule_repository(&self) -> Result<Self::ShiftScheduleRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ShiftSchedule")
    }

    type CustomerTypeRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn customer_type_repository(&self) -> Result<Self::CustomerTypeRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("CustomerType")
    }

    type CustomerProfileRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn customer_profile_repository(&self) -> Result<Self::CustomerProfileRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("CustomerProfile")
    }

    type ContactPersonRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn contact_person_repository(&self) -> Result<Self::ContactPersonRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ContactPerson")
    }

    type CustomerFeedbackRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn customer_feedback_repository(&self) -> Result<Self::CustomerFeedbackRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("CustomerFeedback")
    }

    type LoyaltyProgramRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn loyalty_program_repository(&self) -> Result<Self::LoyaltyProgramRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("LoyaltyProgram")
    }

    type ServiceCategoryRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn service_category_repository(&self) -> Result<Self::ServiceCategoryRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ServiceCategory")
    }

    type ServiceCatalogRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn service_catalog_repository(&self) -> Result<Self::ServiceCatalogRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ServiceCatalog")
    }

    type BoxRentalRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn box_rental_repository(&self) -> Result<Self::BoxRentalRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("BoxRental")
    }

    type ServiceBundleRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn service_bundle_repository(&self) -> Result<Self::ServiceBundleRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ServiceBundle")
    }

    type CampaignStatusRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn campaign_status_repository(&self) -> Result<Self::CampaignStatusRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("CampaignStatus")
    }

    type MarketingCampaignRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn marketing_campaign_repository(&self) -> Result<Self::MarketingCampaignRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("MarketingCampaign")
    }

    type SalesLeadRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn sales_lead_repository(&self) -> Result<Self::SalesLeadRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("SalesLead")
    }

    type PaymentMethodRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn payment_method_repository(&self) -> Result<Self::PaymentMethodRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("PaymentMethod")
    }

    type InvoiceDocumentRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn invoice_document_repository(&self) -> Result<Self::InvoiceDocumentRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("InvoiceDocument")
    }

    type PaymentRecordRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn payment_record_repository(&self) -> Result<Self::PaymentRecordRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("PaymentRecord")
    }

    type ExpenseRecordRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn expense_record_repository(&self) -> Result<Self::ExpenseRecordRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ExpenseRecord")
    }

    type VehicleTypeRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn vehicle_type_repository(&self) -> Result<Self::VehicleTypeRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("VehicleType")
    }

    type FleetVehicleRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn fleet_vehicle_repository(&self) -> Result<Self::FleetVehicleRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("FleetVehicle")
    }

    type EquipmentItemRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn equipment_item_repository(&self) -> Result<Self::EquipmentItemRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("EquipmentItem")
    }

    type MaintenanceScheduleRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn maintenance_schedule_repository(&self) -> Result<Self::MaintenanceScheduleRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("MaintenanceSchedule")
    }

    type FuelLogRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn fuel_log_repository(&self) -> Result<Self::FuelLogRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("FuelLog")
    }

    type UserRoleRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn user_role_repository(&self) -> Result<Self::UserRoleRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("UserRole")
    }

    type NotificationTypeRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn notification_type_repository(&self) -> Result<Self::NotificationTypeRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("NotificationType")
    }

    type UserAccountRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn user_account_repository(&self) -> Result<Self::UserAccountRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("UserAccount")
    }

    type RoleDefinitionRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn role_definition_repository(&self) -> Result<Self::RoleDefinitionRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("RoleDefinition")
    }

    type RoleAssignmentRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn role_assignment_repository(&self) -> Result<Self::RoleAssignmentRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("RoleAssignment")
    }

    type AuditLogRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn audit_log_repository(&self) -> Result<Self::AuditLogRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("AuditLog")
    }

    type ServiceContractRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn service_contract_repository(&self) -> Result<Self::ServiceContractRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ServiceContract")
    }
}

pub(crate) async fn execute_facets<C>(
    ctx: &C,
    outer_query: &SelectQuery,
    options: &QueryOptions,
) -> Result<BTreeMap<String, SmartList<Record>>, RuntimeError>
where
    C: TeaqlRuntime + ?Sized,
{
    let mut facets = BTreeMap::new();
    for facet in &options.facets {
        let mut selection = facet.query.clone();
        merge_outer_filter_into_facet_aggregates(&mut selection, outer_query);
        if !facet.include_all_facets {
            selection = restrict_facet_to_outer_query(ctx, selection, outer_query, &facet.relation_name)?;
        }
        let relation_aggregates = runtime_relation_aggregates(&selection.query_options);
        let query = apply_runtime_metadata(
            selection.query,
            &selection.query_options,
            &selection.child_enhancements,
        );
        let entity = query.entity.clone();
        let mut chain = outer_query.trace_chain.clone();
        chain.push(teaql_core::TraceNode::new(
            query.entity.clone(),
            None,
            facet.facet_name.clone(),
        ));

        let query = PurposedSelectQuery::new(
            query,
            format!("Calculate facet {}", facet.facet_name),
        );
        let facet_rows = ctx.fetch_facet_smart_list(&entity, &query, &relation_aggregates, chain).await?;
        facets.insert(facet.facet_name.clone(), facet_rows);
    }
    Ok(facets)
}

pub(crate) fn restrict_facet_to_outer_query<C>(
    ctx: &C,
    mut selection: QuerySelection,
    outer_query: &SelectQuery,
    relation_name: &str,
) -> Result<QuerySelection, RuntimeError>
where
    C: TeaqlRuntime + ?Sized,
{
    let descriptor = ctx
        .user_context()
        .entity(&outer_query.entity)
        .cloned()
        .ok_or_else(|| RuntimeError::Graph(format!("missing entity: {}", outer_query.entity)))?;
    let relation = descriptor
        .relation_by_name(relation_name)
        .cloned()
        .ok_or_else(|| RuntimeError::MissingRelation {
            entity: outer_query.entity.clone(),
            relation: relation_name.to_owned(),
        })?;
    let mut subquery = outer_query.clone();
    subquery.projection.clear();
    subquery.expr_projection.clear();
    subquery.order_by.clear();
    subquery.slice = None;
    subquery.aggregates.clear();
    subquery.group_by.clear();
    subquery.relations.clear();
    selection.query = selection.query.and_filter(Expr::in_subquery(
        relation.foreign_key,
        descriptor,
        subquery,
        relation.local_key,
    ));
    Ok(selection)
}
