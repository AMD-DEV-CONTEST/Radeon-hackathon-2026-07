
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
    type CompanyRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn company_repository(&self) -> Result<Self::CompanyRepository<'_>, ContextError>;
    type UserAccountRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn user_account_repository(&self) -> Result<Self::UserAccountRepository<'_>, ContextError>;
    type RoleDefinitionRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn role_definition_repository(&self) -> Result<Self::RoleDefinitionRepository<'_>, ContextError>;
    type UserRoleRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn user_role_repository(&self) -> Result<Self::UserRoleRepository<'_>, ContextError>;
    type AuditLogRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn audit_log_repository(&self) -> Result<Self::AuditLogRepository<'_>, ContextError>;
    type NotificationRuleRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn notification_rule_repository(&self) -> Result<Self::NotificationRuleRepository<'_>, ContextError>;
    type DocumentStorageRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn document_storage_repository(&self) -> Result<Self::DocumentStorageRepository<'_>, ContextError>;
    type EmployeeRecordRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn employee_record_repository(&self) -> Result<Self::EmployeeRecordRepository<'_>, ContextError>;
    type PayrollCalculationRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn payroll_calculation_repository(&self) -> Result<Self::PayrollCalculationRepository<'_>, ContextError>;
    type WorkedHoursRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn worked_hours_repository(&self) -> Result<Self::WorkedHoursRepository<'_>, ContextError>;
    type BonusRecordRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn bonus_record_repository(&self) -> Result<Self::BonusRecordRepository<'_>, ContextError>;
    type LeaveRequestRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn leave_request_repository(&self) -> Result<Self::LeaveRequestRepository<'_>, ContextError>;
    type PrivateCustomerRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn private_customer_repository(&self) -> Result<Self::PrivateCustomerRepository<'_>, ContextError>;
    type CorporateCustomerRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn corporate_customer_repository(&self) -> Result<Self::CorporateCustomerRepository<'_>, ContextError>;
    type LinkedContactRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn linked_contact_repository(&self) -> Result<Self::LinkedContactRepository<'_>, ContextError>;
    type BillingInfoRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn billing_info_repository(&self) -> Result<Self::BillingInfoRepository<'_>, ContextError>;
    type InteractionHistoryRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn interaction_history_repository(&self) -> Result<Self::InteractionHistoryRepository<'_>, ContextError>;
    type VehicleAssetRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn vehicle_asset_repository(&self) -> Result<Self::VehicleAssetRepository<'_>, ContextError>;
    type EquipmentItemRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn equipment_item_repository(&self) -> Result<Self::EquipmentItemRepository<'_>, ContextError>;
    type ConsumableItemRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn consumable_item_repository(&self) -> Result<Self::ConsumableItemRepository<'_>, ContextError>;
    type MaintenanceScheduleRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn maintenance_schedule_repository(&self) -> Result<Self::MaintenanceScheduleRepository<'_>, ContextError>;
    type InventoryTrackingRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn inventory_tracking_repository(&self) -> Result<Self::InventoryTrackingRepository<'_>, ContextError>;
    type InsurancePolicyRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn insurance_policy_repository(&self) -> Result<Self::InsurancePolicyRepository<'_>, ContextError>;
    type AddressRecordRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn address_record_repository(&self) -> Result<Self::AddressRecordRepository<'_>, ContextError>;
    type MoveOrderRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn move_order_repository(&self) -> Result<Self::MoveOrderRepository<'_>, ContextError>;
    type RoutePlanRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn route_plan_repository(&self) -> Result<Self::RoutePlanRepository<'_>, ContextError>;
    type TimeSlotRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn time_slot_repository(&self) -> Result<Self::TimeSlotRepository<'_>, ContextError>;
    type FulfillmentEventRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn fulfillment_event_repository(&self) -> Result<Self::FulfillmentEventRepository<'_>, ContextError>;
    type JobAssignmentRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn job_assignment_repository(&self) -> Result<Self::JobAssignmentRepository<'_>, ContextError>;
    type ServiceCatalogRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn service_catalog_repository(&self) -> Result<Self::ServiceCatalogRepository<'_>, ContextError>;
    type ServiceConfigRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn service_config_repository(&self) -> Result<Self::ServiceConfigRepository<'_>, ContextError>;
    type BoxRentalRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn box_rental_repository(&self) -> Result<Self::BoxRentalRepository<'_>, ContextError>;
    type MarketingCampaignRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn marketing_campaign_repository(&self) -> Result<Self::MarketingCampaignRepository<'_>, ContextError>;
    type DiscountCodeRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn discount_code_repository(&self) -> Result<Self::DiscountCodeRepository<'_>, ContextError>;
    type LeadTrackingRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn lead_tracking_repository(&self) -> Result<Self::LeadTrackingRepository<'_>, ContextError>;
    type ConversionMetricRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn conversion_metric_repository(&self) -> Result<Self::ConversionMetricRepository<'_>, ContextError>;
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
    type VatRecordRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn vat_record_repository(&self) -> Result<Self::VatRecordRepository<'_>, ContextError>;
    type FinancialSummaryRepository<'a>: TeaqlEntityRepository + 'a
    where
        Self: 'a;

    fn financial_summary_repository(&self) -> Result<Self::FinancialSummaryRepository<'_>, ContextError>;
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
    type CompanyRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn company_repository(&self) -> Result<Self::CompanyRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("Company")
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

    type UserRoleRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn user_role_repository(&self) -> Result<Self::UserRoleRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("UserRole")
    }

    type AuditLogRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn audit_log_repository(&self) -> Result<Self::AuditLogRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("AuditLog")
    }

    type NotificationRuleRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn notification_rule_repository(&self) -> Result<Self::NotificationRuleRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("NotificationRule")
    }

    type DocumentStorageRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn document_storage_repository(&self) -> Result<Self::DocumentStorageRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("DocumentStorage")
    }

    type EmployeeRecordRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn employee_record_repository(&self) -> Result<Self::EmployeeRecordRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("EmployeeRecord")
    }

    type PayrollCalculationRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn payroll_calculation_repository(&self) -> Result<Self::PayrollCalculationRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("PayrollCalculation")
    }

    type WorkedHoursRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn worked_hours_repository(&self) -> Result<Self::WorkedHoursRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("WorkedHours")
    }

    type BonusRecordRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn bonus_record_repository(&self) -> Result<Self::BonusRecordRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("BonusRecord")
    }

    type LeaveRequestRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn leave_request_repository(&self) -> Result<Self::LeaveRequestRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("LeaveRequest")
    }

    type PrivateCustomerRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn private_customer_repository(&self) -> Result<Self::PrivateCustomerRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("PrivateCustomer")
    }

    type CorporateCustomerRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn corporate_customer_repository(&self) -> Result<Self::CorporateCustomerRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("CorporateCustomer")
    }

    type LinkedContactRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn linked_contact_repository(&self) -> Result<Self::LinkedContactRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("LinkedContact")
    }

    type BillingInfoRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn billing_info_repository(&self) -> Result<Self::BillingInfoRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("BillingInfo")
    }

    type InteractionHistoryRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn interaction_history_repository(&self) -> Result<Self::InteractionHistoryRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("InteractionHistory")
    }

    type VehicleAssetRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn vehicle_asset_repository(&self) -> Result<Self::VehicleAssetRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("VehicleAsset")
    }

    type EquipmentItemRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn equipment_item_repository(&self) -> Result<Self::EquipmentItemRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("EquipmentItem")
    }

    type ConsumableItemRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn consumable_item_repository(&self) -> Result<Self::ConsumableItemRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ConsumableItem")
    }

    type MaintenanceScheduleRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn maintenance_schedule_repository(&self) -> Result<Self::MaintenanceScheduleRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("MaintenanceSchedule")
    }

    type InventoryTrackingRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn inventory_tracking_repository(&self) -> Result<Self::InventoryTrackingRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("InventoryTracking")
    }

    type InsurancePolicyRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn insurance_policy_repository(&self) -> Result<Self::InsurancePolicyRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("InsurancePolicy")
    }

    type AddressRecordRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn address_record_repository(&self) -> Result<Self::AddressRecordRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("AddressRecord")
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

    type TimeSlotRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn time_slot_repository(&self) -> Result<Self::TimeSlotRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("TimeSlot")
    }

    type FulfillmentEventRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn fulfillment_event_repository(&self) -> Result<Self::FulfillmentEventRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("FulfillmentEvent")
    }

    type JobAssignmentRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn job_assignment_repository(&self) -> Result<Self::JobAssignmentRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("JobAssignment")
    }

    type ServiceCatalogRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn service_catalog_repository(&self) -> Result<Self::ServiceCatalogRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ServiceCatalog")
    }

    type ServiceConfigRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn service_config_repository(&self) -> Result<Self::ServiceConfigRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ServiceConfig")
    }

    type BoxRentalRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn box_rental_repository(&self) -> Result<Self::BoxRentalRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("BoxRental")
    }

    type MarketingCampaignRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn marketing_campaign_repository(&self) -> Result<Self::MarketingCampaignRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("MarketingCampaign")
    }

    type DiscountCodeRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn discount_code_repository(&self) -> Result<Self::DiscountCodeRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("DiscountCode")
    }

    type LeadTrackingRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn lead_tracking_repository(&self) -> Result<Self::LeadTrackingRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("LeadTracking")
    }

    type ConversionMetricRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn conversion_metric_repository(&self) -> Result<Self::ConversionMetricRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("ConversionMetric")
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

    type VatRecordRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn vat_record_repository(&self) -> Result<Self::VatRecordRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("VatRecord")
    }

    type FinancialSummaryRepository<'a> = teaql_runtime::EntityDataService<'a, crate::runtime::DataServiceExecutor>
    where
        Self: 'a;

    fn financial_summary_repository(&self) -> Result<Self::FinancialSummaryRepository<'_>, ContextError> {
        self.entity_data_service::<crate::runtime::DataServiceExecutor>("FinancialSummary")
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
