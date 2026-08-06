
use std::collections::BTreeMap;
use crate::TeaqlRuntime;
use crate::Q;
use teaql_core::Entity;
use crate::request_support::TeaqlUserContextExt;
use crate::request_support::AuditedSave;

pub trait IntoU64 {
    fn into_u64(self) -> u64;
}

impl IntoU64 for u64 {
    fn into_u64(self) -> u64 {
        self
    }
}

impl IntoU64 for Option<&teaql_core::Value> {
    fn into_u64(self) -> u64 {
        self.and_then(|v| v.try_u64()).unwrap_or_default()
    }
}

#[derive(Debug, Copy, Clone)]
pub enum SampleDataScale {
    Tiny,
    Small,
    Medium,
}

pub struct SampleDataPlan {
    pub scale: SampleDataScale,
    pub seed: u64,
}

impl SampleDataPlan {
    pub fn small() -> Self {
        Self {
            scale: SampleDataScale::Small,
            seed: 0,
        }
    }
}

pub struct SampleDataReport {
    pub generated: BTreeMap<&'static str, usize>,
    pub skipped: Vec<SampleDataSkipped>,
}

pub struct SampleDataSkipped {
    pub entity: &'static str,
    pub reason: String,
}

pub struct SampleDataState {
    pub plan: SampleDataPlan,
    pub references: BTreeMap<&'static str, Vec<u64>>,
    pub generated: BTreeMap<&'static str, usize>,
    pub skipped: Vec<SampleDataSkipped>,
}

impl SampleDataState {
    pub fn new(plan: SampleDataPlan) -> Self {
        Self {
            plan,
            references: BTreeMap::new(),
            generated: BTreeMap::new(),
            skipped: Vec::new(),
        }
    }

    pub fn add_reference(&mut self, entity: &'static str, id: u64) {
        self.references.entry(entity).or_default().push(id);
    }

    pub fn ids(&self, entity: &'static str) -> &[u64] {
        self.references.get(entity).map(|v| v.as_slice()).unwrap_or(&[])
    }

    pub fn pick_id(&self, entity: &'static str, salt: usize) -> Option<u64> {
        let ids = self.ids(entity);
        if ids.is_empty() {
            None
        } else {
            Some(ids[salt % ids.len()])
        }
    }

    pub fn pick_unused_id(&self, entity: &'static str, salt: usize, used: &std::collections::HashSet<u64>) -> Option<u64> {
        let ids = self.ids(entity);
        if ids.is_empty() {
            return None;
        }

        let best_id = ids[salt % ids.len()];
        if !used.contains(&best_id) {
            return Some(best_id);
        }

        for id in ids {
            if !used.contains(id) {
                return Some(*id);
            }
        }

        Some(best_id)
    }

    pub fn record_generated(&mut self, entity: &'static str) {
        *self.generated.entry(entity).or_default() += 1;
    }

    pub fn record_skipped(&mut self, entity: &'static str, reason: String) {
        self.skipped.push(SampleDataSkipped { entity, reason });
    }

    pub fn into_report(self) -> SampleDataReport {
        SampleDataReport {
            generated: self.generated,
            skipped: self.skipped,
        }
    }
}

pub async fn generate_sample_data<C>(
    ctx: &C,
    plan: SampleDataPlan,
) -> Result<SampleDataReport, String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    log::info!("Starting sample data generation. Scale: {:?}, Seed: {}", plan.scale, plan.seed);
    let mut state = SampleDataState::new(plan);

    load_root_company_profiles(ctx, &mut state).await?; //depth: 0

    load_constant_campaign_statuses(ctx, &mut state).await?;
    load_constant_customer_types(ctx, &mut state).await?;
    load_constant_job_titles(ctx, &mut state).await?;
    load_constant_move_statuses(ctx, &mut state).await?;
    load_constant_notification_types(ctx, &mut state).await?;
    load_constant_payment_methods(ctx, &mut state).await?;
    load_constant_service_categories(ctx, &mut state).await?;
    load_constant_user_roles(ctx, &mut state).await?;
    load_constant_vehicle_types(ctx, &mut state).await?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_equipment_items(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_location_addresses(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_role_definitions(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_service_bundles(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_employee_registries(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_fleet_vehicles(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_marketing_campaigns(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_service_catalogs(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_user_accounts(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_customer_profiles(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_fuel_logs(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_maintenance_schedules(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_payroll_calculations(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_role_assignments(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_shift_schedules(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_contact_persons(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_loyalty_programs(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_move_orders(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_sales_leads(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_service_contracts(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_audit_logs(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_box_rentals(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_customer_feedback(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_expense_records(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_fulfillment_events(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_invoice_documents(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_job_assignments(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_route_plans(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_payment_records(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_worked_hourses(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;


    let report = state.into_report();
    log::info!("Sample data generation completed successfully. Generated: {} tables, Skipped: {} tables.", report.generated.len(), report.skipped.len());
    Ok(report)
}

async fn load_root_company_profiles<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::company_profiles().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference(crate::CompanyProfile::ENTITY_NAME, item.id().into_u64());
    }
    Ok(())
}

async fn load_constant_campaign_statuses<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::campaign_statuses().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference(crate::CampaignStatus::ENTITY_NAME, item.id().into_u64());
    }
    Ok(())
}

async fn load_constant_customer_types<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::customer_types().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference(crate::CustomerType::ENTITY_NAME, item.id().into_u64());
    }
    Ok(())
}

async fn load_constant_job_titles<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::job_titles().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference(crate::JobTitle::ENTITY_NAME, item.id().into_u64());
    }
    Ok(())
}

async fn load_constant_move_statuses<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::move_statuses().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference(crate::MoveStatus::ENTITY_NAME, item.id().into_u64());
    }
    Ok(())
}

async fn load_constant_notification_types<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::notification_types().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference(crate::NotificationType::ENTITY_NAME, item.id().into_u64());
    }
    Ok(())
}

async fn load_constant_payment_methods<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::payment_methods().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference(crate::PaymentMethod::ENTITY_NAME, item.id().into_u64());
    }
    Ok(())
}

async fn load_constant_service_categories<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::service_categories().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference(crate::ServiceCategory::ENTITY_NAME, item.id().into_u64());
    }
    Ok(())
}

async fn load_constant_user_roles<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::user_roles().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference(crate::UserRole::ENTITY_NAME, item.id().into_u64());
    }
    Ok(())
}

async fn load_constant_vehicle_types<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::vehicle_types().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference(crate::VehicleType::ENTITY_NAME, item.id().into_u64());
    }
    Ok(())
}

async fn generate_equipment_items<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Company Profile").is_empty() {
            state.record_skipped(crate::EquipmentItem::ENTITY_NAME, "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Equipment Item: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Equipment Item (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::equipment_items().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Company Profile", i as usize, &used_refs) {
                    entity.update_company_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_item_name(format!("{} {}", "Hand Truck", i + 1));

                entity.update_serial_number(format!("{} {}", "EQ-001", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_purchase_date(past.format("%Y-%m-%d").to_string());
                }

                entity.update_condition(format!("{} {}", "Good", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::EquipmentItem::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Equipment Item: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Equipment Item.");
    Ok(())
}


async fn generate_location_addresses<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Company Profile").is_empty() {
            state.record_skipped(crate::LocationAddress::ENTITY_NAME, "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Location Address: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Location Address (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::location_addresses().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Company Profile", i as usize, &used_refs) {
                    entity.update_company_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_address_line1(format!("{} {}", "123 Main Street", i + 1));

                entity.update_city_name(format!("{} {}", "Springfield", i + 1));

                entity.update_state_province(format!("{} {}", "IL", i + 1));

                {
                    let max_val: u64 = "62701".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_postal_code(rand_val as i64);
                }

                entity.update_country_code(format!("{} {}", "US", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::LocationAddress::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Location Address: {}/{}", i, fanout);
        }

        state.add_reference(crate::LocationAddress::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Location Address.");
    Ok(())
}


async fn generate_role_definitions<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Company Profile").is_empty() {
            state.record_skipped(crate::RoleDefinition::ENTITY_NAME, "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Role Definition: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Role Definition (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::role_definitions().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Company Profile", i as usize, &used_refs) {
                    entity.update_company_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_role_name(format!("{} {}", "Operations Manager", i + 1));

                entity.update_description_text(format!("{} {}", "Manages daily operations and staff", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::RoleDefinition::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Role Definition: {}/{}", i, fanout);
        }

        state.add_reference(crate::RoleDefinition::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Role Definition.");
    Ok(())
}


async fn generate_service_bundles<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Company Profile").is_empty() {
            state.record_skipped(crate::ServiceBundle::ENTITY_NAME, "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Service Bundle: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Service Bundle (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::service_bundles().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Company Profile", i as usize, &used_refs) {
                    entity.update_company_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_bundle_name(format!("{} {}", "Premium Moving Package", i + 1));

                entity.update_bundle_description(format!("{} {}", "Full service including packing and cleaning", i + 1));

                {
                    let max_val: u64 = "1200.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_bundle_price(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::ServiceBundle::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Service Bundle: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Service Bundle.");
    Ok(())
}


async fn generate_employee_registries<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Company Profile").is_empty() {
            state.record_skipped(crate::EmployeeRegistry::ENTITY_NAME, "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Employee Registry: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Job Title").is_empty() {
            state.record_skipped(crate::EmployeeRegistry::ENTITY_NAME, "Required dependency Job Title is missing in reference pool".to_string());
            log::info!("Skipped generating Employee Registry: Required dependency Job Title is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Employee Registry (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::employee_registries().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Company Profile", i as usize, &used_refs) {
                    entity.update_company_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Job Title", i as usize, &used_refs) {
                    entity.update_job_title_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_employee_name(format!("{} {}", "John Smith", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_hire_date(past.format("%Y-%m-%d").to_string());
                }

                entity.update_ssn_number(format!("{} {}", "123-45-6789", i + 1));

                entity.update_phone_number(format!("{} {}", "555-0100", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_update_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::EmployeeRegistry::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Employee Registry: {}/{}", i, fanout);
        }

        state.add_reference(crate::EmployeeRegistry::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Employee Registry.");
    Ok(())
}


async fn generate_fleet_vehicles<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Company Profile").is_empty() {
            state.record_skipped(crate::FleetVehicle::ENTITY_NAME, "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Fleet Vehicle: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Vehicle Type").is_empty() {
            state.record_skipped(crate::FleetVehicle::ENTITY_NAME, "Required dependency Vehicle Type is missing in reference pool".to_string());
            log::info!("Skipped generating Fleet Vehicle: Required dependency Vehicle Type is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Fleet Vehicle (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::fleet_vehicles().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Company Profile", i as usize, &used_refs) {
                    entity.update_company_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Vehicle Type", i as usize, &used_refs) {
                    entity.update_vehicle_type_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_vehicle_registration(format!("{} {}", "ABC-1234", i + 1));

                entity.update_vehicle_model(format!("{} {}", "Ford Transit 350", i + 1));

                {
                    let max_val: u64 = "3.5".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_capacity_tons(rand_val as i64);
                }

                {
                    let max_val: u64 = "45000.0".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_mileage(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_update_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::FleetVehicle::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Fleet Vehicle: {}/{}", i, fanout);
        }

        state.add_reference(crate::FleetVehicle::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Fleet Vehicle.");
    Ok(())
}


async fn generate_marketing_campaigns<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Company Profile").is_empty() {
            state.record_skipped(crate::MarketingCampaign::ENTITY_NAME, "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Marketing Campaign: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Campaign Status").is_empty() {
            state.record_skipped(crate::MarketingCampaign::ENTITY_NAME, "Required dependency Campaign Status is missing in reference pool".to_string());
            log::info!("Skipped generating Marketing Campaign: Required dependency Campaign Status is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Marketing Campaign (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::marketing_campaigns().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Company Profile", i as usize, &used_refs) {
                    entity.update_company_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Campaign Status", i as usize, &used_refs) {
                    entity.update_campaign_status_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_campaign_name(format!("{} {}", "Summer Moving Special 2025", i + 1));

                entity.update_target_audience(format!("{} {}", "Corporate Clients", i + 1));

                {
                    let max_val: u64 = "8000.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_budget_amount(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_start_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_end_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::MarketingCampaign::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Marketing Campaign: {}/{}", i, fanout);
        }

        state.add_reference(crate::MarketingCampaign::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Marketing Campaign.");
    Ok(())
}


async fn generate_service_catalogs<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Company Profile").is_empty() {
            state.record_skipped(crate::ServiceCatalog::ENTITY_NAME, "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Service Catalog: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Service Category").is_empty() {
            state.record_skipped(crate::ServiceCatalog::ENTITY_NAME, "Required dependency Service Category is missing in reference pool".to_string());
            log::info!("Skipped generating Service Catalog: Required dependency Service Category is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Service Catalog (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::service_catalogs().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Company Profile", i as usize, &used_refs) {
                    entity.update_company_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Service Category", i as usize, &used_refs) {
                    entity.update_service_category_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_service_name(format!("{} {}", "Full Packing Service", i + 1));

                entity.update_service_description(format!("{} {}", "Complete packing and unpacking", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_update_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::ServiceCatalog::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Service Catalog: {}/{}", i, fanout);
        }

        state.add_reference(crate::ServiceCatalog::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Service Catalog.");
    Ok(())
}


async fn generate_user_accounts<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Company Profile").is_empty() {
            state.record_skipped(crate::UserAccount::ENTITY_NAME, "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating User Account: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("User Role").is_empty() {
            state.record_skipped(crate::UserAccount::ENTITY_NAME, "Required dependency User Role is missing in reference pool".to_string());
            log::info!("Skipped generating User Account: Required dependency User Role is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for User Account (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::user_accounts().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Company Profile", i as usize, &used_refs) {
                    entity.update_company_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("User Role", i as usize, &used_refs) {
                    entity.update_user_role_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_account_name(format!("{} {}", "admin_user", i + 1));

                entity.update_email_address(format!("{} {}", "admin@swiftmove.com", i + 1));

                entity.update_password_hash(format!("{} {}", "hashed_secret_value", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_update_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::UserAccount::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating User Account: {}/{}", i, fanout);
        }

        state.add_reference(crate::UserAccount::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for User Account.");
    Ok(())
}


async fn generate_customer_profiles<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Type").is_empty() {
            state.record_skipped(crate::CustomerProfile::ENTITY_NAME, "Required dependency Customer Type is missing in reference pool".to_string());
            log::info!("Skipped generating Customer Profile: Required dependency Customer Type is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Employee Registry").is_empty() {
            state.record_skipped(crate::CustomerProfile::ENTITY_NAME, "Required dependency Employee Registry is missing in reference pool".to_string());
            log::info!("Skipped generating Customer Profile: Required dependency Employee Registry is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Customer Profile (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::customer_profiles().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Type", i as usize, &used_refs) {
                    entity.update_customer_type_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Employee Registry", i as usize, &used_refs) {
                    entity.update_account_manager_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_profile_type(format!("{} {}", "Corporate", i + 1));

                entity.update_customer_name(format!("{} {}", "Acme Corporation", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_update_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::CustomerProfile::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Customer Profile: {}/{}", i, fanout);
        }

        state.add_reference(crate::CustomerProfile::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Customer Profile.");
    Ok(())
}


async fn generate_fuel_logs<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Fleet Vehicle").is_empty() {
            state.record_skipped(crate::FuelLog::ENTITY_NAME, "Required dependency Fleet Vehicle is missing in reference pool".to_string());
            log::info!("Skipped generating Fuel Log: Required dependency Fleet Vehicle is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Fuel Log (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::fuel_logs().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Fleet Vehicle", i as usize, &used_refs) {
                    entity.update_asset_vehicle_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let max_val: u64 = "45.0".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_fuel_amount(rand_val as i64);
                }

                {
                    let max_val: u64 = "162.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_fuel_cost(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_fuel_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let max_val: u64 = "45120.0".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_odometer_reading(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::FuelLog::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Fuel Log: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Fuel Log.");
    Ok(())
}


async fn generate_maintenance_schedules<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Fleet Vehicle").is_empty() {
            state.record_skipped(crate::MaintenanceSchedule::ENTITY_NAME, "Required dependency Fleet Vehicle is missing in reference pool".to_string());
            log::info!("Skipped generating Maintenance Schedule: Required dependency Fleet Vehicle is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Maintenance Schedule (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::maintenance_schedules().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Fleet Vehicle", i as usize, &used_refs) {
                    entity.update_asset_vehicle_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_maintenance_type(format!("{} {}", "Oil Change", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_scheduled_date(past.format("%Y-%m-%d").to_string());
                }

                entity.update_description(format!("{} {}", "Scheduled oil change and inspection", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::MaintenanceSchedule::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Maintenance Schedule: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Maintenance Schedule.");
    Ok(())
}


async fn generate_payroll_calculations<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Employee Registry").is_empty() {
            state.record_skipped(crate::PayrollCalculation::ENTITY_NAME, "Required dependency Employee Registry is missing in reference pool".to_string());
            log::info!("Skipped generating Payroll Calculation: Required dependency Employee Registry is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Payroll Calculation (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::payroll_calculations().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Employee Registry", i as usize, &used_refs) {
                    entity.update_employee_record_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_pay_period(format!("{} {}", "June 2025", i + 1));

                {
                    let max_val: u64 = "3500.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_base_salary(rand_val as i64);
                }

                {
                    let max_val: u64 = "5.0".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_overtime_hours(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::PayrollCalculation::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Payroll Calculation: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Payroll Calculation.");
    Ok(())
}


async fn generate_role_assignments<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("User Account").is_empty() {
            state.record_skipped(crate::RoleAssignment::ENTITY_NAME, "Required dependency User Account is missing in reference pool".to_string());
            log::info!("Skipped generating Role Assignment: Required dependency User Account is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Role Definition").is_empty() {
            state.record_skipped(crate::RoleAssignment::ENTITY_NAME, "Required dependency Role Definition is missing in reference pool".to_string());
            log::info!("Skipped generating Role Assignment: Required dependency Role Definition is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Role Assignment (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::role_assignments().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("User Account", i as usize, &used_refs) {
                    entity.update_user_account_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Role Definition", i as usize, &used_refs) {
                    entity.update_role_definition_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_assign_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::RoleAssignment::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Role Assignment: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Role Assignment.");
    Ok(())
}


async fn generate_shift_schedules<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Employee Registry").is_empty() {
            state.record_skipped(crate::ShiftSchedule::ENTITY_NAME, "Required dependency Employee Registry is missing in reference pool".to_string());
            log::info!("Skipped generating Shift Schedule: Required dependency Employee Registry is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Shift Schedule (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::shift_schedules().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Employee Registry", i as usize, &used_refs) {
                    entity.update_employee_record_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_shift_date(past.format("%Y-%m-%d").to_string());
                }

                entity.update_start_time(format!("{} {}", "00:00", i + 1));

                entity.update_end_time(format!("{} {}", "00:00", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::ShiftSchedule::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Shift Schedule: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Shift Schedule.");
    Ok(())
}


async fn generate_contact_persons<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Profile").is_empty() {
            state.record_skipped(crate::ContactPerson::ENTITY_NAME, "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Contact Person: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Contact Person (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::contact_persons().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_contact_name(format!("{} {}", "Jane Williams", i + 1));

                entity.update_phone_number(format!("{} {}", "555-0200", i + 1));

                entity.update_email_address(format!("{} {}", "jane@acmecorp.com", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::ContactPerson::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Contact Person: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Contact Person.");
    Ok(())
}


async fn generate_loyalty_programs<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Profile").is_empty() {
            state.record_skipped(crate::LoyaltyProgram::ENTITY_NAME, "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Loyalty Program: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Loyalty Program (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::loyalty_programs().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_program_name(format!("{} {}", "Gold Member", i + 1));

                {
                    let max_val: u64 = "1500".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_points_balance(rand_val as i64);
                }

                entity.update_tier_level(format!("{} {}", "Gold", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::LoyaltyProgram::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Loyalty Program: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Loyalty Program.");
    Ok(())
}


async fn generate_move_orders<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Profile").is_empty() {
            state.record_skipped(crate::MoveOrder::ENTITY_NAME, "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Move Order: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Location Address").is_empty() {
            state.record_skipped(crate::MoveOrder::ENTITY_NAME, "Required dependency Location Address is missing in reference pool".to_string());
            log::info!("Skipped generating Move Order: Required dependency Location Address is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Location Address").is_empty() {
            state.record_skipped(crate::MoveOrder::ENTITY_NAME, "Required dependency Location Address is missing in reference pool".to_string());
            log::info!("Skipped generating Move Order: Required dependency Location Address is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Move Status").is_empty() {
            state.record_skipped(crate::MoveOrder::ENTITY_NAME, "Required dependency Move Status is missing in reference pool".to_string());
            log::info!("Skipped generating Move Order: Required dependency Move Status is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Move Order (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::move_orders().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Location Address", i as usize, &used_refs) {
                    entity.update_origin_address_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Location Address", i as usize, &used_refs) {
                    entity.update_destination_address_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Move Status", i as usize, &used_refs) {
                    entity.update_move_status_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_move_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let max_val: u64 = "2500.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_estimated_weight(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_update_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::MoveOrder::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Move Order: {}/{}", i, fanout);
        }

        state.add_reference(crate::MoveOrder::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Move Order.");
    Ok(())
}


async fn generate_sales_leads<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Marketing Campaign").is_empty() {
            state.record_skipped(crate::SalesLead::ENTITY_NAME, "Required dependency Marketing Campaign is missing in reference pool".to_string());
            log::info!("Skipped generating Sales Lead: Required dependency Marketing Campaign is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Customer Profile").is_empty() {
            state.record_skipped(crate::SalesLead::ENTITY_NAME, "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Sales Lead: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Sales Lead (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::sales_leads().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Marketing Campaign", i as usize, &used_refs) {
                    entity.update_marketing_campaign_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_lead_source(format!("{} {}", "Referral", i + 1));

                entity.update_lead_status(format!("{} {}", "Qualified", i + 1));

                {
                    let max_val: u64 = "3000.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_estimated_value(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::SalesLead::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Sales Lead: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Sales Lead.");
    Ok(())
}


async fn generate_service_contracts<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Profile").is_empty() {
            state.record_skipped(crate::ServiceContract::ENTITY_NAME, "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Service Contract: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Service Contract (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::service_contracts().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_contract_status(format!("{} {}", "Active", i + 1));

                entity.update_contract_number(format!("{} {}", "CTR-2025-001", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_start_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_end_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let max_val: u64 = "50000.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_contract_value(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::ServiceContract::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Service Contract: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Service Contract.");
    Ok(())
}


async fn generate_audit_logs<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("User Account").is_empty() {
            state.record_skipped(crate::AuditLog::ENTITY_NAME, "Required dependency User Account is missing in reference pool".to_string());
            log::info!("Skipped generating Audit Log: Required dependency User Account is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Move Order").is_empty() {
            state.record_skipped(crate::AuditLog::ENTITY_NAME, "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Audit Log: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Audit Log (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::audit_logs().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("User Account", i as usize, &used_refs) {
                    entity.update_action_operator_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Move Order", i as usize, &used_refs) {
                    entity.update_entity_reference_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_log_timestamp(past.format("%Y-%m-%d").to_string());
                }

                entity.update_action_type(format!("{} {}", "move_created", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::AuditLog::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Audit Log: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Audit Log.");
    Ok(())
}


async fn generate_box_rentals<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Move Order").is_empty() {
            state.record_skipped(crate::BoxRental::ENTITY_NAME, "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Box Rental: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Service Catalog").is_empty() {
            state.record_skipped(crate::BoxRental::ENTITY_NAME, "Required dependency Service Catalog is missing in reference pool".to_string());
            log::info!("Skipped generating Box Rental: Required dependency Service Catalog is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Box Rental (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::box_rentals().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Move Order", i as usize, &used_refs) {
                    entity.update_move_order_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Service Catalog", i as usize, &used_refs) {
                    entity.update_service_catalog_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let max_val: u64 = "30".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_box_quantity(rand_val as i64);
                }

                {
                    let max_val: u64 = "75.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_rental_fee(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_return_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::BoxRental::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Box Rental: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Box Rental.");
    Ok(())
}


async fn generate_customer_feedback<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Profile").is_empty() {
            state.record_skipped(crate::CustomerFeedback::ENTITY_NAME, "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Customer Feedback: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Move Order").is_empty() {
            state.record_skipped(crate::CustomerFeedback::ENTITY_NAME, "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Customer Feedback: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Customer Feedback (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::customer_feedback().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Move Order", i as usize, &used_refs) {
                    entity.update_move_order_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_feedback_comment(format!("{} {}", "Great service", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_feedback_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::CustomerFeedback::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Customer Feedback: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Customer Feedback.");
    Ok(())
}


async fn generate_expense_records<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Move Order").is_empty() {
            state.record_skipped(crate::ExpenseRecord::ENTITY_NAME, "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Expense Record: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Expense Record (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::expense_records().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Move Order", i as usize, &used_refs) {
                    entity.update_move_order_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_expense_category(format!("{} {}", "Fuel", i + 1));

                entity.update_expense_description(format!("{} {}", "Diesel fuel for route", i + 1));

                {
                    let max_val: u64 = "185.50".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_expense_amount(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_expense_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::ExpenseRecord::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Expense Record: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Expense Record.");
    Ok(())
}


async fn generate_fulfillment_events<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Move Order").is_empty() {
            state.record_skipped(crate::FulfillmentEvent::ENTITY_NAME, "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Fulfillment Event: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Fulfillment Event (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::fulfillment_events().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Move Order", i as usize, &used_refs) {
                    entity.update_move_order_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_event_type(format!("{} {}", "Arrived at origin", i + 1));

                entity.update_event_description(format!("{} {}", "Truck arrived at customer location", i + 1));

                entity.update_event_time(format!("{} {}", "15:00", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::FulfillmentEvent::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Fulfillment Event: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Fulfillment Event.");
    Ok(())
}


async fn generate_invoice_documents<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Profile").is_empty() {
            state.record_skipped(crate::InvoiceDocument::ENTITY_NAME, "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Invoice Document: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Move Order").is_empty() {
            state.record_skipped(crate::InvoiceDocument::ENTITY_NAME, "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Invoice Document: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Invoice Document (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::invoice_documents().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Move Order", i as usize, &used_refs) {
                    entity.update_move_order_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_invoice_number(format!("{} {}", "INV-2025-0042", i + 1));

                {
                    let max_val: u64 = "2800.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_invoice_total(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_issue_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_due_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::InvoiceDocument::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Invoice Document: {}/{}", i, fanout);
        }

        state.add_reference(crate::InvoiceDocument::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Invoice Document.");
    Ok(())
}


async fn generate_job_assignments<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Move Order").is_empty() {
            state.record_skipped(crate::JobAssignment::ENTITY_NAME, "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Job Assignment: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Employee Registry").is_empty() {
            state.record_skipped(crate::JobAssignment::ENTITY_NAME, "Required dependency Employee Registry is missing in reference pool".to_string());
            log::info!("Skipped generating Job Assignment: Required dependency Employee Registry is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Job Assignment (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::job_assignments().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Move Order", i as usize, &used_refs) {
                    entity.update_move_order_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Employee Registry", i as usize, &used_refs) {
                    entity.update_employee_record_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_assignment_role(format!("{} {}", "Driver", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_assignment_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::JobAssignment::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Job Assignment: {}/{}", i, fanout);
        }

        state.add_reference(crate::JobAssignment::ENTITY_NAME, entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Job Assignment.");
    Ok(())
}


async fn generate_route_plans<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Move Order").is_empty() {
            state.record_skipped(crate::RoutePlan::ENTITY_NAME, "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Route Plan: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Route Plan (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::route_plans().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Move Order", i as usize, &used_refs) {
                    entity.update_move_order_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_route_description(format!("{} {}", "I-55 South via Decatur", i + 1));

                {
                    let max_val: u64 = "320.5".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_estimated_distance(rand_val as i64);
                }

                {
                    let max_val: u64 = "240".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_estimated_duration(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::RoutePlan::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Route Plan: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Route Plan.");
    Ok(())
}


async fn generate_payment_records<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Profile").is_empty() {
            state.record_skipped(crate::PaymentRecord::ENTITY_NAME, "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Payment Record: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Move Order").is_empty() {
            state.record_skipped(crate::PaymentRecord::ENTITY_NAME, "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Payment Record: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Invoice Document").is_empty() {
            state.record_skipped(crate::PaymentRecord::ENTITY_NAME, "Required dependency Invoice Document is missing in reference pool".to_string());
            log::info!("Skipped generating Payment Record: Required dependency Invoice Document is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Payment Method").is_empty() {
            state.record_skipped(crate::PaymentRecord::ENTITY_NAME, "Required dependency Payment Method is missing in reference pool".to_string());
            log::info!("Skipped generating Payment Record: Required dependency Payment Method is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Payment Record (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::payment_records().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Move Order", i as usize, &used_refs) {
                    entity.update_move_order_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Invoice Document", i as usize, &used_refs) {
                    entity.update_invoice_document_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Payment Method", i as usize, &used_refs) {
                    entity.update_payment_method_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let max_val: u64 = "2800.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_payment_amount(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_payment_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::PaymentRecord::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Payment Record: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Payment Record.");
    Ok(())
}


async fn generate_worked_hourses<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Job Assignment").is_empty() {
            state.record_skipped(crate::WorkedHours::ENTITY_NAME, "Required dependency Job Assignment is missing in reference pool".to_string());
            log::info!("Skipped generating Worked Hours: Required dependency Job Assignment is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Employee Registry").is_empty() {
            state.record_skipped(crate::WorkedHours::ENTITY_NAME, "Required dependency Employee Registry is missing in reference pool".to_string());
            log::info!("Skipped generating Worked Hours: Required dependency Employee Registry is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Worked Hours (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::worked_hourses().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Job Assignment", i as usize, &used_refs) {
                    entity.update_job_assignment_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Employee Registry", i as usize, &used_refs) {
                    entity.update_employee_record_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let max_val: u64 = "8.5".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_hours_logged(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_work_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated(crate::WorkedHours::ENTITY_NAME);

        if i % 20 == 0 {
            log::info!("Generating Worked Hours: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Worked Hours.");
    Ok(())
}
