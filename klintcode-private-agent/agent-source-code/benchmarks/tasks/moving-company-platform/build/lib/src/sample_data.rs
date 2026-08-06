
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

    load_constant_order_statuses(ctx, &mut state).await?;

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
        Box::pin(generate_location_addresses(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_marketing_campaigns(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_role_definitions(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_service_catalogs(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_consumable_items(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_customer_profiles(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_discount_codes(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_equipment_items(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_insurance_policies(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_leave_requests(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_maintenance_schedules(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_notification_rules(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_payroll_calculations(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_service_configs(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_user_accounts(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_billing_info(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_bonus_records(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_contact_persons(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_document_storage(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_interaction_histories(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_inventory_trackings(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_move_orders(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_role_assignments(ctx, &mut state)).await.map_err(|e| {
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
        Box::pin(generate_conversion_metrics(ctx, &mut state)).await.map_err(|e| {
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
        Box::pin(generate_payment_records(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_route_plans(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_time_slots(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_financial_summaries(ctx, &mut state)).await.map_err(|e| {
            teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(e))
        })
    }).await.map_err(|e| e.to_string())?;

    ctx.user_context().transaction_data(|| async {
        Box::pin(generate_vat_records(ctx, &mut state)).await.map_err(|e| {
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
        state.add_reference("Company Profile", item.id().into_u64());
    }
    Ok(())
}

async fn load_constant_order_statuses<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
    let list = Q::order_statuses().purpose("Init Sample Data").execute_for_list(ctx).await.unwrap_or_default();
    for item in list {
        state.add_reference("Order Status", item.id().into_u64());
    }
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
            state.record_skipped("Employee Registry", "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Employee Registry: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
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
                entity.update_employee_name(format!("{} {}", "John Doe", i + 1));

                entity.update_job_title(format!("{} {}", "Driver", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_hire_date(past.format("%Y-%m-%d").to_string());
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

        state.record_generated("Employee Registry");

        if i % 20 == 0 {
            log::info!("Generating Employee Registry: {}/{}", i, fanout);
        }

        state.add_reference("Employee Registry", entity.id().into_u64());
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
            state.record_skipped("Fleet Vehicle", "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Fleet Vehicle: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
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
                entity.update_vehicle_registration(format!("{} {}", "ABC-123", i + 1));

                entity.update_vehicle_model(format!("{} {}", "Ford Transit", i + 1));

                {
                    let max_val: u64 = "5.0".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_capacity_tons(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Fleet Vehicle");

        if i % 20 == 0 {
            log::info!("Generating Fleet Vehicle: {}/{}", i, fanout);
        }

        state.add_reference("Fleet Vehicle", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Fleet Vehicle.");
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
            state.record_skipped("Location Address", "Required dependency Company Profile is missing in reference pool".to_string());
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
                entity.update_street_line(format!("{} {}", "123 Main St", i + 1));

                entity.update_city_name(format!("{} {}", "Metropolis", i + 1));

                {
                    let max_val: u64 = "12345".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_postal_code(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Location Address");

        if i % 20 == 0 {
            log::info!("Generating Location Address: {}/{}", i, fanout);
        }

        state.add_reference("Location Address", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Location Address.");
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
            state.record_skipped("Marketing Campaign", "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Marketing Campaign: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
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
                entity.update_campaign_name(format!("{} {}", "Summer Special 2025", i + 1));

                entity.update_target_audience(format!("{} {}", "Corporates", i + 1));

                {
                    let max_val: u64 = "5000.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_budget_amount(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Marketing Campaign");

        if i % 20 == 0 {
            log::info!("Generating Marketing Campaign: {}/{}", i, fanout);
        }

        state.add_reference("Marketing Campaign", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Marketing Campaign.");
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
            state.record_skipped("Role Definition", "Required dependency Company Profile is missing in reference pool".to_string());
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
                entity.update_role_name(format!("{} {}", "Admin Role", i + 1));

                entity.update_description_text(format!("{} {}", "Administrator role", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Role Definition");

        if i % 20 == 0 {
            log::info!("Generating Role Definition: {}/{}", i, fanout);
        }

        state.add_reference("Role Definition", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Role Definition.");
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
            state.record_skipped("Service Catalog", "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Service Catalog: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
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
                entity.update_service_name(format!("{} {}", "Deep Cleaning", i + 1));

                entity.update_service_description(format!("{} {}", "Full packing service", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Service Catalog");

        if i % 20 == 0 {
            log::info!("Generating Service Catalog: {}/{}", i, fanout);
        }

        state.add_reference("Service Catalog", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Service Catalog.");
    Ok(())
}


async fn generate_consumable_items<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Fleet Vehicle").is_empty() {
            state.record_skipped("Consumable Item", "Required dependency Fleet Vehicle is missing in reference pool".to_string());
            log::info!("Skipped generating Consumable Item: Required dependency Fleet Vehicle is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Consumable Item (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::consumable_items().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Fleet Vehicle", i as usize, &used_refs) {
                    entity.update_asset_vehicle_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_item_name(format!("{} {}", "Packing Tape", i + 1));

                {
                    let max_val: u64 = "50".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_quantity_count(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Consumable Item");

        if i % 20 == 0 {
            log::info!("Generating Consumable Item: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Consumable Item.");
    Ok(())
}


async fn generate_customer_profiles<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Employee Registry").is_empty() {
            state.record_skipped("Customer Profile", "Required dependency Employee Registry is missing in reference pool".to_string());
            log::info!("Skipped generating Customer Profile: Required dependency Employee Registry is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
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

                if let Some(ref_id) = state.pick_unused_id("Employee Registry", i as usize, &used_refs) {
                    entity.update_account_manager_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_profile_type(format!("{} {}", "Corporate", i + 1));

                entity.update_customer_name(format!("{} {}", "Acme Corp", i + 1));

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

        state.record_generated("Customer Profile");

        if i % 20 == 0 {
            log::info!("Generating Customer Profile: {}/{}", i, fanout);
        }

        state.add_reference("Customer Profile", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Customer Profile.");
    Ok(())
}


async fn generate_discount_codes<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Marketing Campaign").is_empty() {
            state.record_skipped("Discount Code", "Required dependency Marketing Campaign is missing in reference pool".to_string());
            log::info!("Skipped generating Discount Code: Required dependency Marketing Campaign is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Discount Code (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::discount_codes().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Marketing Campaign", i as usize, &used_refs) {
                    entity.update_marketing_campaign_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_code_value(format!("{} {}", "SUMMER25", i + 1));

                {
                    let max_val: u64 = "10".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_discount_percent(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Discount Code");

        if i % 20 == 0 {
            log::info!("Generating Discount Code: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Discount Code.");
    Ok(())
}


async fn generate_equipment_items<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Fleet Vehicle").is_empty() {
            state.record_skipped("Equipment Item", "Required dependency Fleet Vehicle is missing in reference pool".to_string());
            log::info!("Skipped generating Equipment Item: Required dependency Fleet Vehicle is missing in reference pool.");
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

                if let Some(ref_id) = state.pick_unused_id("Fleet Vehicle", i as usize, &used_refs) {
                    entity.update_asset_vehicle_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_item_name(format!("{} {}", "Dolly", i + 1));

                entity.update_serial_number(format!("{} {}", "DLY-001", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Equipment Item");

        if i % 20 == 0 {
            log::info!("Generating Equipment Item: {}/{}", i, fanout);
        }

        state.add_reference("Equipment Item", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Equipment Item.");
    Ok(())
}


async fn generate_insurance_policies<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Fleet Vehicle").is_empty() {
            state.record_skipped("Insurance Policy", "Required dependency Fleet Vehicle is missing in reference pool".to_string());
            log::info!("Skipped generating Insurance Policy: Required dependency Fleet Vehicle is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Insurance Policy (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::insurance_policies().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Fleet Vehicle", i as usize, &used_refs) {
                    entity.update_fleet_vehicle_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_policy_number(format!("{} {}", "POL-12345", i + 1));

                entity.update_provider_name(format!("{} {}", "SafeDrive Insurance", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_expiry_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Insurance Policy");

        if i % 20 == 0 {
            log::info!("Generating Insurance Policy: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Insurance Policy.");
    Ok(())
}


async fn generate_leave_requests<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Employee Registry").is_empty() {
            state.record_skipped("Leave Request", "Required dependency Employee Registry is missing in reference pool".to_string());
            log::info!("Skipped generating Leave Request: Required dependency Employee Registry is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Leave Request (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::leave_requests().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Employee Registry", i as usize, &used_refs) {
                    entity.update_employee_record_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_leave_reason(format!("{} {}", "Vacation", i + 1));

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

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_update_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Leave Request");

        if i % 20 == 0 {
            log::info!("Generating Leave Request: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Leave Request.");
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
            state.record_skipped("Maintenance Schedule", "Required dependency Fleet Vehicle is missing in reference pool".to_string());
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

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Maintenance Schedule");

        if i % 20 == 0 {
            log::info!("Generating Maintenance Schedule: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Maintenance Schedule.");
    Ok(())
}


async fn generate_notification_rules<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Role Definition").is_empty() {
            state.record_skipped("Notification Rule", "Required dependency Role Definition is missing in reference pool".to_string());
            log::info!("Skipped generating Notification Rule: Required dependency Role Definition is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Notification Rule (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::notification_rules().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Role Definition", i as usize, &used_refs) {
                    entity.update_role_definition_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_rule_name(format!("{} {}", "Notify on Error", i + 1));

                entity.update_event_trigger(format!("{} {}", "error_event", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Notification Rule");

        if i % 20 == 0 {
            log::info!("Generating Notification Rule: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Notification Rule.");
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
            state.record_skipped("Payroll Calculation", "Required dependency Employee Registry is missing in reference pool".to_string());
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
                    let max_val: u64 = "3000.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_base_salary(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Payroll Calculation");

        if i % 20 == 0 {
            log::info!("Generating Payroll Calculation: {}/{}", i, fanout);
        }

        state.add_reference("Payroll Calculation", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Payroll Calculation.");
    Ok(())
}


async fn generate_service_configs<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Service Catalog").is_empty() {
            state.record_skipped("Service Config", "Required dependency Service Catalog is missing in reference pool".to_string());
            log::info!("Skipped generating Service Config: Required dependency Service Catalog is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Service Config (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::service_configs().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Service Catalog", i as usize, &used_refs) {
                    entity.update_service_catalog_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_config_name(format!("{} {}", "Standard", i + 1));

                {
                    let max_val: u64 = "200.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_price_amount(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Service Config");

        if i % 20 == 0 {
            log::info!("Generating Service Config: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Service Config.");
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
            state.record_skipped("User Account", "Required dependency Company Profile is missing in reference pool".to_string());
            log::info!("Skipped generating User Account: Required dependency Company Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Employee Registry").is_empty() {
            state.record_skipped("User Account", "Required dependency Employee Registry is missing in reference pool".to_string());
            log::info!("Skipped generating User Account: Required dependency Employee Registry is missing in reference pool.");
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
                if let Some(ref_id) = state.pick_unused_id("Employee Registry", i as usize, &used_refs) {
                    entity.update_employee_registry_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_account_name(format!("{} {}", "admin_user", i + 1));

                entity.update_email_address(format!("{} {}", "admin@example.com", i + 1));

                entity.update_password_hash(format!("{} {}", "secret123", i + 1));

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

        state.record_generated("User Account");

        if i % 20 == 0 {
            log::info!("Generating User Account: {}/{}", i, fanout);
        }

        state.add_reference("User Account", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for User Account.");
    Ok(())
}


async fn generate_billing_info<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Profile").is_empty() {
            state.record_skipped("Billing Info", "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Billing Info: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Billing Info (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::billing_info().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_billing_address(format!("{} {}", "123 Corporate Blvd", i + 1));

                entity.update_tax_id(format!("{} {}", "US123456789", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Billing Info");

        if i % 20 == 0 {
            log::info!("Generating Billing Info: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Billing Info.");
    Ok(())
}


async fn generate_bonus_records<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Employee Registry").is_empty() {
            state.record_skipped("Bonus Record", "Required dependency Employee Registry is missing in reference pool".to_string());
            log::info!("Skipped generating Bonus Record: Required dependency Employee Registry is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Payroll Calculation").is_empty() {
            state.record_skipped("Bonus Record", "Required dependency Payroll Calculation is missing in reference pool".to_string());
            log::info!("Skipped generating Bonus Record: Required dependency Payroll Calculation is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Bonus Record (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::bonus_records().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Employee Registry", i as usize, &used_refs) {
                    entity.update_employee_record_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Payroll Calculation", i as usize, &used_refs) {
                    entity.update_payroll_calculation_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_bonus_reason(format!("{} {}", "Good performance", i + 1));

                {
                    let max_val: u64 = "500.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_bonus_amount(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Bonus Record");

        if i % 20 == 0 {
            log::info!("Generating Bonus Record: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Bonus Record.");
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
            state.record_skipped("Contact Person", "Required dependency Customer Profile is missing in reference pool".to_string());
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
                entity.update_contact_name(format!("{} {}", "Jane Smith", i + 1));

                entity.update_phone_number(format!("{} {}", "555-0199", i + 1));

                entity.update_email_address(format!("{} {}", "jane@acme.com", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Contact Person");

        if i % 20 == 0 {
            log::info!("Generating Contact Person: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Contact Person.");
    Ok(())
}


async fn generate_document_storage<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Profile").is_empty() {
            state.record_skipped("Document Storage", "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Document Storage: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Document Storage (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::document_storage().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_document_name(format!("{} {}", "Contract PDF", i + 1));

                entity.update_file_url(format!("{} {}", "//example.com/doc.pdf", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Document Storage");

        if i % 20 == 0 {
            log::info!("Generating Document Storage: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Document Storage.");
    Ok(())
}


async fn generate_interaction_histories<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Customer Profile").is_empty() {
            state.record_skipped("Interaction History", "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Interaction History: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Employee Registry").is_empty() {
            state.record_skipped("Interaction History", "Required dependency Employee Registry is missing in reference pool".to_string());
            log::info!("Skipped generating Interaction History: Required dependency Employee Registry is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Interaction History (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::interaction_histories().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Customer Profile", i as usize, &used_refs) {
                    entity.update_customer_profile_id(ref_id);
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
                entity.update_interaction_notes(format!("{} {}", "Discussed moving plan", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_interaction_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Interaction History");

        if i % 20 == 0 {
            log::info!("Generating Interaction History: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Interaction History.");
    Ok(())
}


async fn generate_inventory_trackings<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Equipment Item").is_empty() {
            state.record_skipped("Inventory Tracking", "Required dependency Equipment Item is missing in reference pool".to_string());
            log::info!("Skipped generating Inventory Tracking: Required dependency Equipment Item is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Inventory Tracking (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::inventory_trackings().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Equipment Item", i as usize, &used_refs) {
                    entity.update_equipment_item_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_location_name(format!("{} {}", "Warehouse A", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_check_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Inventory Tracking");

        if i % 20 == 0 {
            log::info!("Generating Inventory Tracking: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Inventory Tracking.");
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
            state.record_skipped("Move Order", "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Move Order: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Location Address").is_empty() {
            state.record_skipped("Move Order", "Required dependency Location Address is missing in reference pool".to_string());
            log::info!("Skipped generating Move Order: Required dependency Location Address is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Location Address").is_empty() {
            state.record_skipped("Move Order", "Required dependency Location Address is missing in reference pool".to_string());
            log::info!("Skipped generating Move Order: Required dependency Location Address is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Fleet Vehicle").is_empty() {
            state.record_skipped("Move Order", "Required dependency Fleet Vehicle is missing in reference pool".to_string());
            log::info!("Skipped generating Move Order: Required dependency Fleet Vehicle is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Order Status").is_empty() {
            state.record_skipped("Move Order", "Required dependency Order Status is missing in reference pool".to_string());
            log::info!("Skipped generating Move Order: Required dependency Order Status is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1 + 1 + 1 + 1;
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
                if let Some(ref_id) = state.pick_unused_id("Fleet Vehicle", i as usize, &used_refs) {
                    entity.update_asset_vehicle_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                if let Some(ref_id) = state.pick_unused_id("Order Status", i as usize, &used_refs) {
                    entity.update_order_status_id(ref_id);
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

        state.record_generated("Move Order");

        if i % 20 == 0 {
            log::info!("Generating Move Order: {}/{}", i, fanout);
        }

        state.add_reference("Move Order", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Move Order.");
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
            state.record_skipped("Role Assignment", "Required dependency User Account is missing in reference pool".to_string());
            log::info!("Skipped generating Role Assignment: Required dependency User Account is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Role Definition").is_empty() {
            state.record_skipped("Role Assignment", "Required dependency Role Definition is missing in reference pool".to_string());
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

        state.record_generated("Role Assignment");

        if i % 20 == 0 {
            log::info!("Generating Role Assignment: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Role Assignment.");
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
            state.record_skipped("Sales Lead", "Required dependency Marketing Campaign is missing in reference pool".to_string());
            log::info!("Skipped generating Sales Lead: Required dependency Marketing Campaign is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Customer Profile").is_empty() {
            state.record_skipped("Sales Lead", "Required dependency Customer Profile is missing in reference pool".to_string());
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
                entity.update_lead_source(format!("{} {}", "Web Form", i + 1));

                entity.update_lead_status(format!("{} {}", "Converted", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Sales Lead");

        if i % 20 == 0 {
            log::info!("Generating Sales Lead: {}/{}", i, fanout);
        }

        state.add_reference("Sales Lead", entity.id().into_u64());
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
            state.record_skipped("Service Contract", "Required dependency Customer Profile is missing in reference pool".to_string());
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



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Service Contract");

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
            state.record_skipped("Audit Log", "Required dependency User Account is missing in reference pool".to_string());
            log::info!("Skipped generating Audit Log: Required dependency User Account is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Move Order").is_empty() {
            state.record_skipped("Audit Log", "Required dependency Move Order is missing in reference pool".to_string());
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

        state.record_generated("Audit Log");

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
            state.record_skipped("Box Rental", "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Box Rental: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Service Catalog").is_empty() {
            state.record_skipped("Box Rental", "Required dependency Service Catalog is missing in reference pool".to_string());
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
                    let max_val: u64 = "20".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_box_quantity(rand_val as i64);
                }

                {
                    let max_val: u64 = "50.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_rental_fee(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Box Rental");

        if i % 20 == 0 {
            log::info!("Generating Box Rental: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Box Rental.");
    Ok(())
}


async fn generate_conversion_metrics<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Sales Lead").is_empty() {
            state.record_skipped("Conversion Metric", "Required dependency Sales Lead is missing in reference pool".to_string());
            log::info!("Skipped generating Conversion Metric: Required dependency Sales Lead is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Conversion Metric (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::conversion_metrics().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Sales Lead", i as usize, &used_refs) {
                    entity.update_sales_lead_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let max_val: u64 = "1500.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_conversion_value(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_conversion_date(past.format("%Y-%m-%d").to_string());
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Conversion Metric");

        if i % 20 == 0 {
            log::info!("Generating Conversion Metric: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Conversion Metric.");
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
            state.record_skipped("Expense Record", "Required dependency Move Order is missing in reference pool".to_string());
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
                entity.update_expense_description(format!("{} {}", "Fuel", i + 1));

                {
                    let max_val: u64 = "100.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_expense_amount(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Expense Record");

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
            state.record_skipped("Fulfillment Event", "Required dependency Move Order is missing in reference pool".to_string());
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
                entity.update_event_description(format!("{} {}", "Arrived at origin", i + 1));

                entity.update_event_time(format!("{} {}", "15:00", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Fulfillment Event");

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
            state.record_skipped("Invoice Document", "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Invoice Document: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Move Order").is_empty() {
            state.record_skipped("Invoice Document", "Required dependency Move Order is missing in reference pool".to_string());
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
                {
                    let max_val: u64 = "1500.00".parse().unwrap_or(1000);
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
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Invoice Document");

        if i % 20 == 0 {
            log::info!("Generating Invoice Document: {}/{}", i, fanout);
        }

        state.add_reference("Invoice Document", entity.id().into_u64());
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
            state.record_skipped("Job Assignment", "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Job Assignment: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Employee Registry").is_empty() {
            state.record_skipped("Job Assignment", "Required dependency Employee Registry is missing in reference pool".to_string());
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
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



        let entity = entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Job Assignment");

        if i % 20 == 0 {
            log::info!("Generating Job Assignment: {}/{}", i, fanout);
        }

        state.add_reference("Job Assignment", entity.id().into_u64());
    }

    log::info!("Successfully generated sample records for Job Assignment.");
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
            state.record_skipped("Payment Record", "Required dependency Customer Profile is missing in reference pool".to_string());
            log::info!("Skipped generating Payment Record: Required dependency Customer Profile is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Move Order").is_empty() {
            state.record_skipped("Payment Record", "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Payment Record: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1 + 1;
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
                {
                    let max_val: u64 = "1500.00".parse().unwrap_or(1000);
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

        state.record_generated("Payment Record");

        if i % 20 == 0 {
            log::info!("Generating Payment Record: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Payment Record.");
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
            state.record_skipped("Route Plan", "Required dependency Move Order is missing in reference pool".to_string());
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
                {
                    let max_val: u64 = "50.5".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_estimated_distance(rand_val as i64);
                }

                {
                    let max_val: u64 = "120".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_estimated_duration(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Route Plan");

        if i % 20 == 0 {
            log::info!("Generating Route Plan: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Route Plan.");
    Ok(())
}


async fn generate_time_slots<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Move Order").is_empty() {
            state.record_skipped("Time Slot", "Required dependency Move Order is missing in reference pool".to_string());
            log::info!("Skipped generating Time Slot: Required dependency Move Order is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Time Slot (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::time_slots().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Move Order", i as usize, &used_refs) {
                    entity.update_move_order_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                entity.update_start_time(format!("{} {}", "00:00", i + 1));

                entity.update_end_time(format!("{} {}", "00:00", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Time Slot");

        if i % 20 == 0 {
            log::info!("Generating Time Slot: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Time Slot.");
    Ok(())
}


async fn generate_financial_summaries<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Invoice Document").is_empty() {
            state.record_skipped("Financial Summary", "Required dependency Invoice Document is missing in reference pool".to_string());
            log::info!("Skipped generating Financial Summary: Required dependency Invoice Document is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for Financial Summary (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::financial_summaries().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Invoice Document", i as usize, &used_refs) {
                    entity.update_invoice_document_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let max_val: u64 = "1200.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_total_revenue(rand_val as i64);
                }

                entity.update_report_month(format!("{} {}", "May 2025", i + 1));

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("Financial Summary");

        if i % 20 == 0 {
            log::info!("Generating Financial Summary: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Financial Summary.");
    Ok(())
}


async fn generate_vat_records<C>(
    ctx: &C,
    state: &mut SampleDataState,
) -> Result<(), String>
where
    C: TeaqlRuntime + ?Sized + crate::TeaqlRepositoryProvider,
{
        if state.ids("Invoice Document").is_empty() {
            state.record_skipped("VAT Record", "Required dependency Invoice Document is missing in reference pool".to_string());
            log::info!("Skipped generating VAT Record: Required dependency Invoice Document is missing in reference pool.");
            return Ok(());
        }


    let object_fields_count = 0 + 1;
    let base_fanout = std::cmp::max(1, object_fields_count) * 20;

    let fanout = match state.plan.scale {
        SampleDataScale::Tiny => base_fanout,
        SampleDataScale::Small => base_fanout * 5,
        SampleDataScale::Medium => base_fanout * 50,
    };

    log::info!("Generating sample data for VAT Record (expected: {})...", fanout);

    for i in 0..fanout {
        let mut entity = Q::vat_records().purpose("Init Sample Data").new_entity(ctx);
        let mut used_refs = std::collections::HashSet::new();

                if let Some(ref_id) = state.pick_unused_id("Invoice Document", i as usize, &used_refs) {
                    entity.update_invoice_document_id(ref_id);
                    used_refs.insert(ref_id);
                } else {
                    // Optional relation was missing in reference pool
                }
                {
                    let max_val: u64 = "20.0".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_vat_percent(rand_val as i64);
                }

                {
                    let max_val: u64 = "300.00".parse().unwrap_or(1000);
                    let rand_val = (i as u64 + state.plan.seed) % max_val.max(1) + 1;
                    entity.update_vat_amount(rand_val as i64);
                }

                {
                    let days = ((i as u64 + state.plan.seed) % (365 * 3)) as i64;
                    let past = chrono::Utc::now().naive_utc() - chrono::Duration::try_days(days).unwrap_or_default();
                    entity.update_create_time(past.format("%Y-%m-%d").to_string());
                }



entity.audit_as("Init Sample Data").save(ctx).await.map_err(|e| e.to_string())?;

        state.record_generated("VAT Record");

        if i % 20 == 0 {
            log::info!("Generating VAT Record: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for VAT Record.");
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
            state.record_skipped("Worked Hours", "Required dependency Job Assignment is missing in reference pool".to_string());
            log::info!("Skipped generating Worked Hours: Required dependency Job Assignment is missing in reference pool.");
            return Ok(());
        }

        if state.ids("Employee Registry").is_empty() {
            state.record_skipped("Worked Hours", "Required dependency Employee Registry is missing in reference pool".to_string());
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
                    let max_val: u64 = "4.5".parse().unwrap_or(1000);
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

        state.record_generated("Worked Hours");

        if i % 20 == 0 {
            log::info!("Generating Worked Hours: {}/{}", i, fanout);
        }

    }

    log::info!("Successfully generated sample records for Worked Hours.");
    Ok(())
}
