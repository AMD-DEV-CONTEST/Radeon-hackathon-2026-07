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
    pub fn addresses() -> AddressRequest {
        AddressRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn addresses_minimal() -> AddressRequest {
        AddressRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn addresses_with_children() -> AddressRequest {
        AddressRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn moving_events() -> MovingEventRequest {
        MovingEventRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn moving_events_minimal() -> MovingEventRequest {
        MovingEventRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn moving_events_with_children() -> MovingEventRequest {
        MovingEventRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn routes() -> RouteRequest {
        RouteRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn routes_minimal() -> RouteRequest {
        RouteRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn routes_with_children() -> RouteRequest {
        RouteRequest::new()
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

    pub fn staffs() -> StaffRequest {
        StaffRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn staffs_minimal() -> StaffRequest {
        StaffRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn staffs_with_children() -> StaffRequest {
        StaffRequest::new()
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

    pub fn payrolls() -> PayrollRequest {
        PayrollRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn payrolls_minimal() -> PayrollRequest {
        PayrollRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn payrolls_with_children() -> PayrollRequest {
        PayrollRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn bonuses() -> BonusRequest {
        BonusRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn bonuses_minimal() -> BonusRequest {
        BonusRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn bonuses_with_children() -> BonusRequest {
        BonusRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn leave_trackings() -> LeaveTrackingRequest {
        LeaveTrackingRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn leave_trackings_minimal() -> LeaveTrackingRequest {
        LeaveTrackingRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn leave_trackings_with_children() -> LeaveTrackingRequest {
        LeaveTrackingRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn private_customers() -> PrivateCustomerRequest {
        PrivateCustomerRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn private_customers_minimal() -> PrivateCustomerRequest {
        PrivateCustomerRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn private_customers_with_children() -> PrivateCustomerRequest {
        PrivateCustomerRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn corporate_customers() -> CorporateCustomerRequest {
        CorporateCustomerRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn corporate_customers_minimal() -> CorporateCustomerRequest {
        CorporateCustomerRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn corporate_customers_with_children() -> CorporateCustomerRequest {
        CorporateCustomerRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn customer_contacts() -> CustomerContactRequest {
        CustomerContactRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn customer_contacts_minimal() -> CustomerContactRequest {
        CustomerContactRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn customer_contacts_with_children() -> CustomerContactRequest {
        CustomerContactRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn moving_services() -> MovingServiceRequest {
        MovingServiceRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn moving_services_minimal() -> MovingServiceRequest {
        MovingServiceRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn moving_services_with_children() -> MovingServiceRequest {
        MovingServiceRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn cleaning_services() -> CleaningServiceRequest {
        CleaningServiceRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn cleaning_services_minimal() -> CleaningServiceRequest {
        CleaningServiceRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn cleaning_services_with_children() -> CleaningServiceRequest {
        CleaningServiceRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn campaigns() -> CampaignRequest {
        CampaignRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn campaigns_minimal() -> CampaignRequest {
        CampaignRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn campaigns_with_children() -> CampaignRequest {
        CampaignRequest::new()
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

    pub fn leads() -> LeadRequest {
        LeadRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn leads_minimal() -> LeadRequest {
        LeadRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn leads_with_children() -> LeadRequest {
        LeadRequest::new()
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

    pub fn payments() -> PaymentRequest {
        PaymentRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn payments_minimal() -> PaymentRequest {
        PaymentRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn payments_with_children() -> PaymentRequest {
        PaymentRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn invoices() -> InvoiceRequest {
        InvoiceRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn invoices_minimal() -> InvoiceRequest {
        InvoiceRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn invoices_with_children() -> InvoiceRequest {
        InvoiceRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn expenses() -> ExpenseRequest {
        ExpenseRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn expenses_minimal() -> ExpenseRequest {
        ExpenseRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn expenses_with_children() -> ExpenseRequest {
        ExpenseRequest::new()
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

    pub fn vehicles() -> VehicleRequest {
        VehicleRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn vehicles_minimal() -> VehicleRequest {
        VehicleRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn vehicles_with_children() -> VehicleRequest {
        VehicleRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn equipment() -> EquipmentRequest {
        EquipmentRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn equipment_minimal() -> EquipmentRequest {
        EquipmentRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn equipment_with_children() -> EquipmentRequest {
        EquipmentRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn consumables() -> ConsumableRequest {
        ConsumableRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn consumables_minimal() -> ConsumableRequest {
        ConsumableRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn consumables_with_children() -> ConsumableRequest {
        ConsumableRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn users() -> UserRequest {
        UserRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn users_minimal() -> UserRequest {
        UserRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn users_with_children() -> UserRequest {
        UserRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn roles() -> RoleRequest {
        RoleRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn roles_minimal() -> RoleRequest {
        RoleRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn roles_with_children() -> RoleRequest {
        RoleRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn permissions() -> PermissionRequest {
        PermissionRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn permissions_minimal() -> PermissionRequest {
        PermissionRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn permissions_with_children() -> PermissionRequest {
        PermissionRequest::new()
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

    pub fn role_permissions() -> RolePermissionRequest {
        RolePermissionRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn role_permissions_minimal() -> RolePermissionRequest {
        RolePermissionRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn role_permissions_with_children() -> RolePermissionRequest {
        RolePermissionRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn authentication_logs() -> AuthenticationLogRequest {
        AuthenticationLogRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn authentication_logs_minimal() -> AuthenticationLogRequest {
        AuthenticationLogRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn authentication_logs_with_children() -> AuthenticationLogRequest {
        AuthenticationLogRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn activity_logs() -> ActivityLogRequest {
        ActivityLogRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn activity_logs_minimal() -> ActivityLogRequest {
        ActivityLogRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn activity_logs_with_children() -> ActivityLogRequest {
        ActivityLogRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn notifications() -> NotificationRequest {
        NotificationRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn notifications_minimal() -> NotificationRequest {
        NotificationRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn notifications_with_children() -> NotificationRequest {
        NotificationRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn api_endpoints() -> ApiEndpointRequest {
        ApiEndpointRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn api_endpoints_minimal() -> ApiEndpointRequest {
        ApiEndpointRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn api_endpoints_with_children() -> ApiEndpointRequest {
        ApiEndpointRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn webhooks() -> WebhookRequest {
        WebhookRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn webhooks_minimal() -> WebhookRequest {
        WebhookRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn webhooks_with_children() -> WebhookRequest {
        WebhookRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }
}