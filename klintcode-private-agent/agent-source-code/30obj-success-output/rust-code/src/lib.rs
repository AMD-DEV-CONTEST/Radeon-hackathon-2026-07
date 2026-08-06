use teaql_core::SmartList;
use platform_modules_core::{Q, Address, Bonus, ConversionMetric, FulfillmentEvent, User, AuthenticationLog, VatRecord, MovingService, TeaqlRepositoryProvider};

pub fn generated_domain_crate() -> &'static str {
    "platform-modules-core"
}

pub async fn query_address(
    ctx: &impl TeaqlRepositoryProvider, 
) -> Result<SmartList<Address>, Box<dyn std::error::Error>>
{
    let rows = Q::addresses_minimal()
        .select_street()
        .select_city()
        .select_state()
        .select_postal_code()
        .select_country()
        .select_create_time()
        .select_update_time()
        .purpose("why")
        .execute_for_list(ctx).await?;
    Ok(rows)
}

pub async fn query_bonus(
    ctx: &impl TeaqlRepositoryProvider, 
) -> Result<SmartList<Bonus>, Box<dyn std::error::Error>>
{
    let rows = Q::bonuses_minimal()
        .select_staff()
        .select_bonus_type()
        .select_amount()
        .select_reason()
        .select_bonus_date()
        .select_create_time()
        .select_update_time()
        .purpose("why")
        .execute_for_list(ctx).await?;
    Ok(rows)
}

pub async fn query_conversion_metric(
    ctx: &impl TeaqlRepositoryProvider, 
) -> Result<SmartList<ConversionMetric>, Box<dyn std::error::Error>>
{
    let rows = Q::conversion_metrics_minimal()
        .select_campaign()
        .select_leads_generated()
        .select_conversions()
        .select_conversion_rate()
        .select_revenue_attributed()
        .select_date_recorded()
        .select_create_time()
        .select_update_time()
        .purpose("why")
        .execute_for_list(ctx).await?;
    Ok(rows)
}

pub async fn query_fulfillment_event(
    ctx: &impl TeaqlRepositoryProvider, 
) -> Result<SmartList<FulfillmentEvent>, Box<dyn std::error::Error>>
{
    let rows = Q::fulfillment_events_minimal()
        .select_event_type()
        .select_event_time()
        .select_description()
        .select_moving_event()
        .select_create_time()
        .select_update_time()
        .purpose("why")
        .execute_for_list(ctx).await?;
    Ok(rows)
}

pub async fn query_moving_service(
    ctx: &impl TeaqlRepositoryProvider, 
) -> Result<SmartList<MovingService>, Box<dyn std::error::Error>>
{
    let rows = Q::moving_services_minimal()
        .select_name()
        .select_service_code()
        .select_base_price()
        .select_description()
        .select_create_time()
        .select_update_time()
        .purpose("why")
        .execute_for_list(ctx).await?;
    Ok(rows)
}

pub async fn query_user(
    ctx: &impl TeaqlRepositoryProvider, 
) -> Result<SmartList<User>, Box<dyn std::error::Error>>
{
    let rows = Q::users_minimal()
        .select_username()
        .select_email()
        .select_password_hash()
        .select_create_time()
        .select_update_time()
        .purpose("why")
        .execute_for_list(ctx).await?;
    Ok(rows)
}

pub async fn query_authentication_log(
    ctx: &impl TeaqlRepositoryProvider, 
) -> Result<SmartList<AuthenticationLog>, Box<dyn std::error::Error>>
{
    let rows = Q::authentication_logs_minimal()
        .select_user()
        .select_login_time()
        .select_ip_address()
        .select_success()
        .select_auth_method()
        .select_create_time()
        .select_update_time()
        .purpose("why")
        .execute_for_list(ctx).await?;
    Ok(rows)
}

pub async fn query_vat_record(
    ctx: &impl TeaqlRepositoryProvider, 
) -> Result<SmartList<VatRecord>, Box<dyn std::error::Error>>
{
    let rows = Q::vat_records_minimal()
        .select_vat_amount()
        .select_tax_period()
        .select_filing_status()
        .select_create_time()
        .select_update_time()
        .purpose("why")
        .execute_for_list(ctx).await?;
    Ok(rows)
}