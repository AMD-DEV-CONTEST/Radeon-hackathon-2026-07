
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("[{}] Starting application...", chrono::Local::now().format("%Y-%m-%d %H:%M:%S%.3f"));
    let _runtime = school_service_core::service_runtime_from_env().await?;
    _runtime.ensure_schema().await?;

    // Uncomment the following line to generate sample data for testing:
    // school_service_core::sample_data::generate_sample_data(&_runtime, school_service_core::sample_data::SampleDataPlan::small()).await?;
    Ok(())
}