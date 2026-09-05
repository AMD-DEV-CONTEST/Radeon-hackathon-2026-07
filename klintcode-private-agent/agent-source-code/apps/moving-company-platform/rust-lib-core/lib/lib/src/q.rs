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
    pub fn move_statuses() -> MoveStatusRequest {
        MoveStatusRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn move_statuses_minimal() -> MoveStatusRequest {
        MoveStatusRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn move_statuses_with_children() -> MoveStatusRequest {
        MoveStatusRequest::new()
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

    pub fn job_titles() -> JobTitleRequest {
        JobTitleRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn job_titles_minimal() -> JobTitleRequest {
        JobTitleRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn job_titles_with_children() -> JobTitleRequest {
        JobTitleRequest::new()
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

    pub fn shift_schedules() -> ShiftScheduleRequest {
        ShiftScheduleRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn shift_schedules_minimal() -> ShiftScheduleRequest {
        ShiftScheduleRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn shift_schedules_with_children() -> ShiftScheduleRequest {
        ShiftScheduleRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn customer_types() -> CustomerTypeRequest {
        CustomerTypeRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn customer_types_minimal() -> CustomerTypeRequest {
        CustomerTypeRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn customer_types_with_children() -> CustomerTypeRequest {
        CustomerTypeRequest::new()
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

    pub fn customer_feedback() -> CustomerFeedbackRequest {
        CustomerFeedbackRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn customer_feedback_minimal() -> CustomerFeedbackRequest {
        CustomerFeedbackRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn customer_feedback_with_children() -> CustomerFeedbackRequest {
        CustomerFeedbackRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn loyalty_programs() -> LoyaltyProgramRequest {
        LoyaltyProgramRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn loyalty_programs_minimal() -> LoyaltyProgramRequest {
        LoyaltyProgramRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn loyalty_programs_with_children() -> LoyaltyProgramRequest {
        LoyaltyProgramRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn service_categories() -> ServiceCategoryRequest {
        ServiceCategoryRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn service_categories_minimal() -> ServiceCategoryRequest {
        ServiceCategoryRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn service_categories_with_children() -> ServiceCategoryRequest {
        ServiceCategoryRequest::new()
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

    pub fn service_bundles() -> ServiceBundleRequest {
        ServiceBundleRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn service_bundles_minimal() -> ServiceBundleRequest {
        ServiceBundleRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn service_bundles_with_children() -> ServiceBundleRequest {
        ServiceBundleRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn campaign_statuses() -> CampaignStatusRequest {
        CampaignStatusRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn campaign_statuses_minimal() -> CampaignStatusRequest {
        CampaignStatusRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn campaign_statuses_with_children() -> CampaignStatusRequest {
        CampaignStatusRequest::new()
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

    pub fn payment_methods() -> PaymentMethodRequest {
        PaymentMethodRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn payment_methods_minimal() -> PaymentMethodRequest {
        PaymentMethodRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn payment_methods_with_children() -> PaymentMethodRequest {
        PaymentMethodRequest::new()
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

    pub fn vehicle_types() -> VehicleTypeRequest {
        VehicleTypeRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn vehicle_types_minimal() -> VehicleTypeRequest {
        VehicleTypeRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn vehicle_types_with_children() -> VehicleTypeRequest {
        VehicleTypeRequest::new()
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

    pub fn fuel_logs() -> FuelLogRequest {
        FuelLogRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn fuel_logs_minimal() -> FuelLogRequest {
        FuelLogRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn fuel_logs_with_children() -> FuelLogRequest {
        FuelLogRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn user_roles() -> UserRoleRequest {
        UserRoleRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn user_roles_minimal() -> UserRoleRequest {
        UserRoleRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn user_roles_with_children() -> UserRoleRequest {
        UserRoleRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn notification_types() -> NotificationTypeRequest {
        NotificationTypeRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn notification_types_minimal() -> NotificationTypeRequest {
        NotificationTypeRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn notification_types_with_children() -> NotificationTypeRequest {
        NotificationTypeRequest::new()
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
}