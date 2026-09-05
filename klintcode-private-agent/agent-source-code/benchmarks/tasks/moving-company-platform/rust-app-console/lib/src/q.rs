use teaql_core::Expr;

use crate::*;

pub struct PurposedQuery<T> {
    pub inner: T,
    pub purpose: String,
}

impl<T> PurposedQuery<T> {
    pub fn new(inner: T, purpose: impl Into<String>) -> Self {
        Self { inner, purpose: purpose.into() }
    }
}

pub struct Q;

impl Q {
    pub fn order_statuses() -> OrderStatusRequest {
        OrderStatusRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn order_statuses_minimal() -> OrderStatusRequest {
        OrderStatusRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn order_statuses_with_children() -> OrderStatusRequest {
        OrderStatusRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn company_profiles() -> CompanyProfileRequest {
        CompanyProfileRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn company_profiles_minimal() -> CompanyProfileRequest {
        CompanyProfileRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn company_profiles_with_children() -> CompanyProfileRequest {
        CompanyProfileRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn user_accounts() -> UserAccountRequest {
        UserAccountRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn user_accounts_minimal() -> UserAccountRequest {
        UserAccountRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn user_accounts_with_children() -> UserAccountRequest {
        UserAccountRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn role_definitions() -> RoleDefinitionRequest {
        RoleDefinitionRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn role_definitions_minimal() -> RoleDefinitionRequest {
        RoleDefinitionRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn role_definitions_with_children() -> RoleDefinitionRequest {
        RoleDefinitionRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn role_assignments() -> RoleAssignmentRequest {
        RoleAssignmentRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn role_assignments_minimal() -> RoleAssignmentRequest {
        RoleAssignmentRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn role_assignments_with_children() -> RoleAssignmentRequest {
        RoleAssignmentRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn notification_rules() -> NotificationRuleRequest {
        NotificationRuleRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn notification_rules_minimal() -> NotificationRuleRequest {
        NotificationRuleRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn notification_rules_with_children() -> NotificationRuleRequest {
        NotificationRuleRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn audit_logs() -> AuditLogRequest {
        AuditLogRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn audit_logs_minimal() -> AuditLogRequest {
        AuditLogRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn audit_logs_with_children() -> AuditLogRequest {
        AuditLogRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn service_contracts() -> ServiceContractRequest {
        ServiceContractRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn service_contracts_minimal() -> ServiceContractRequest {
        ServiceContractRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn service_contracts_with_children() -> ServiceContractRequest {
        ServiceContractRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn document_storage() -> DocumentStorageRequest {
        DocumentStorageRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn document_storage_minimal() -> DocumentStorageRequest {
        DocumentStorageRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn document_storage_with_children() -> DocumentStorageRequest {
        DocumentStorageRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn insurance_policies() -> InsurancePolicyRequest {
        InsurancePolicyRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn insurance_policies_minimal() -> InsurancePolicyRequest {
        InsurancePolicyRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn insurance_policies_with_children() -> InsurancePolicyRequest {
        InsurancePolicyRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn employee_registries() -> EmployeeRegistryRequest {
        EmployeeRegistryRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn employee_registries_minimal() -> EmployeeRegistryRequest {
        EmployeeRegistryRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn employee_registries_with_children() -> EmployeeRegistryRequest {
        EmployeeRegistryRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn leave_requests() -> LeaveRequestRequest {
        LeaveRequestRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn leave_requests_minimal() -> LeaveRequestRequest {
        LeaveRequestRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn leave_requests_with_children() -> LeaveRequestRequest {
        LeaveRequestRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn payroll_calculations() -> PayrollCalculationRequest {
        PayrollCalculationRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn payroll_calculations_minimal() -> PayrollCalculationRequest {
        PayrollCalculationRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn payroll_calculations_with_children() -> PayrollCalculationRequest {
        PayrollCalculationRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn bonus_records() -> BonusRecordRequest {
        BonusRecordRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn bonus_records_minimal() -> BonusRecordRequest {
        BonusRecordRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn bonus_records_with_children() -> BonusRecordRequest {
        BonusRecordRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn job_assignments() -> JobAssignmentRequest {
        JobAssignmentRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn job_assignments_minimal() -> JobAssignmentRequest {
        JobAssignmentRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn job_assignments_with_children() -> JobAssignmentRequest {
        JobAssignmentRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn worked_hourses() -> WorkedHoursRequest {
        WorkedHoursRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn worked_hourses_minimal() -> WorkedHoursRequest {
        WorkedHoursRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn worked_hourses_with_children() -> WorkedHoursRequest {
        WorkedHoursRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn customer_profiles() -> CustomerProfileRequest {
        CustomerProfileRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn customer_profiles_minimal() -> CustomerProfileRequest {
        CustomerProfileRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn customer_profiles_with_children() -> CustomerProfileRequest {
        CustomerProfileRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn contact_persons() -> ContactPersonRequest {
        ContactPersonRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn contact_persons_minimal() -> ContactPersonRequest {
        ContactPersonRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn contact_persons_with_children() -> ContactPersonRequest {
        ContactPersonRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn billing_info() -> BillingInfoRequest {
        BillingInfoRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn billing_info_minimal() -> BillingInfoRequest {
        BillingInfoRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn billing_info_with_children() -> BillingInfoRequest {
        BillingInfoRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn interaction_histories() -> InteractionHistoryRequest {
        InteractionHistoryRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn interaction_histories_minimal() -> InteractionHistoryRequest {
        InteractionHistoryRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn interaction_histories_with_children() -> InteractionHistoryRequest {
        InteractionHistoryRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn marketing_campaigns() -> MarketingCampaignRequest {
        MarketingCampaignRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn marketing_campaigns_minimal() -> MarketingCampaignRequest {
        MarketingCampaignRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn marketing_campaigns_with_children() -> MarketingCampaignRequest {
        MarketingCampaignRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn discount_codes() -> DiscountCodeRequest {
        DiscountCodeRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn discount_codes_minimal() -> DiscountCodeRequest {
        DiscountCodeRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn discount_codes_with_children() -> DiscountCodeRequest {
        DiscountCodeRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn sales_leads() -> SalesLeadRequest {
        SalesLeadRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn sales_leads_minimal() -> SalesLeadRequest {
        SalesLeadRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn sales_leads_with_children() -> SalesLeadRequest {
        SalesLeadRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn conversion_metrics() -> ConversionMetricRequest {
        ConversionMetricRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn conversion_metrics_minimal() -> ConversionMetricRequest {
        ConversionMetricRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn conversion_metrics_with_children() -> ConversionMetricRequest {
        ConversionMetricRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn location_addresses() -> LocationAddressRequest {
        LocationAddressRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn location_addresses_minimal() -> LocationAddressRequest {
        LocationAddressRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn location_addresses_with_children() -> LocationAddressRequest {
        LocationAddressRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn move_orders() -> MoveOrderRequest {
        MoveOrderRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn move_orders_minimal() -> MoveOrderRequest {
        MoveOrderRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn move_orders_with_children() -> MoveOrderRequest {
        MoveOrderRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn route_plans() -> RoutePlanRequest {
        RoutePlanRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn route_plans_minimal() -> RoutePlanRequest {
        RoutePlanRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn route_plans_with_children() -> RoutePlanRequest {
        RoutePlanRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn time_slots() -> TimeSlotRequest {
        TimeSlotRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn time_slots_minimal() -> TimeSlotRequest {
        TimeSlotRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn time_slots_with_children() -> TimeSlotRequest {
        TimeSlotRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn fulfillment_events() -> FulfillmentEventRequest {
        FulfillmentEventRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn fulfillment_events_minimal() -> FulfillmentEventRequest {
        FulfillmentEventRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn fulfillment_events_with_children() -> FulfillmentEventRequest {
        FulfillmentEventRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn fleet_vehicles() -> FleetVehicleRequest {
        FleetVehicleRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn fleet_vehicles_minimal() -> FleetVehicleRequest {
        FleetVehicleRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn fleet_vehicles_with_children() -> FleetVehicleRequest {
        FleetVehicleRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn equipment_items() -> EquipmentItemRequest {
        EquipmentItemRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn equipment_items_minimal() -> EquipmentItemRequest {
        EquipmentItemRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn equipment_items_with_children() -> EquipmentItemRequest {
        EquipmentItemRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn consumable_items() -> ConsumableItemRequest {
        ConsumableItemRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn consumable_items_minimal() -> ConsumableItemRequest {
        ConsumableItemRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn consumable_items_with_children() -> ConsumableItemRequest {
        ConsumableItemRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn maintenance_schedules() -> MaintenanceScheduleRequest {
        MaintenanceScheduleRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn maintenance_schedules_minimal() -> MaintenanceScheduleRequest {
        MaintenanceScheduleRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn maintenance_schedules_with_children() -> MaintenanceScheduleRequest {
        MaintenanceScheduleRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn inventory_trackings() -> InventoryTrackingRequest {
        InventoryTrackingRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn inventory_trackings_minimal() -> InventoryTrackingRequest {
        InventoryTrackingRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn inventory_trackings_with_children() -> InventoryTrackingRequest {
        InventoryTrackingRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn service_catalogs() -> ServiceCatalogRequest {
        ServiceCatalogRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn service_catalogs_minimal() -> ServiceCatalogRequest {
        ServiceCatalogRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn service_catalogs_with_children() -> ServiceCatalogRequest {
        ServiceCatalogRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn service_configs() -> ServiceConfigRequest {
        ServiceConfigRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn service_configs_minimal() -> ServiceConfigRequest {
        ServiceConfigRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn service_configs_with_children() -> ServiceConfigRequest {
        ServiceConfigRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn box_rentals() -> BoxRentalRequest {
        BoxRentalRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn box_rentals_minimal() -> BoxRentalRequest {
        BoxRentalRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn box_rentals_with_children() -> BoxRentalRequest {
        BoxRentalRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn invoice_documents() -> InvoiceDocumentRequest {
        InvoiceDocumentRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn invoice_documents_minimal() -> InvoiceDocumentRequest {
        InvoiceDocumentRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn invoice_documents_with_children() -> InvoiceDocumentRequest {
        InvoiceDocumentRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn payment_records() -> PaymentRecordRequest {
        PaymentRecordRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn payment_records_minimal() -> PaymentRecordRequest {
        PaymentRecordRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn payment_records_with_children() -> PaymentRecordRequest {
        PaymentRecordRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn expense_records() -> ExpenseRecordRequest {
        ExpenseRecordRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn expense_records_minimal() -> ExpenseRecordRequest {
        ExpenseRecordRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn expense_records_with_children() -> ExpenseRecordRequest {
        ExpenseRecordRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn vat_records() -> VatRecordRequest {
        VatRecordRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn vat_records_minimal() -> VatRecordRequest {
        VatRecordRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn vat_records_with_children() -> VatRecordRequest {
        VatRecordRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn financial_summaries() -> FinancialSummaryRequest {
        FinancialSummaryRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn financial_summaries_minimal() -> FinancialSummaryRequest {
        FinancialSummaryRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn financial_summaries_with_children() -> FinancialSummaryRequest {
        FinancialSummaryRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }
}