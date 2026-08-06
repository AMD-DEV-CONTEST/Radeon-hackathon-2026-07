
use school_management_service_core::{E, Q};
use teaql_core::Entity;
use teaql_core::Value;
use school_management_service_core::AuditedSave;

fn value_to_u64(v: &Value) -> u64 {
    match v {
        Value::U64(n) => *n,
        Value::I64(n) => *n as u64,
        _ => panic!("Expected u64 value, got {:?}", v),
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("[{}] Starting School Management System...", chrono::Local::now().format("%Y-%m-%d %H:%M:%S%.3f"));

    // Initialize runtime and ensure schema
    let ctx = school_management_service_core::service_runtime_from_env().await?;
    ctx.ensure_schema().await?;

    // Generate sample data for testing
    school_management_service_core::sample_data::generate_sample_data(
        &ctx,
        school_management_service_core::sample_data::SampleDataPlan::small(),
    )
    .await?;
    println!("✅ Sample data generated successfully.");
    Ok(())
}
