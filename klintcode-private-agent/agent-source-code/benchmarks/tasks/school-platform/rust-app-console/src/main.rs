
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("[{}] Starting application...", chrono::Local::now().format("%Y-%m-%d %H:%M:%S%.3f"));
    let _runtime = school_service_core::service_runtime_from_env().await?;
    _runtime.ensure_schema().await?;

    // Generate sample data for testing
    println!("Generating sample data...");
    school_service_core::sample_data::generate_sample_data(&_runtime, school_service_core::sample_data::SampleDataPlan::small()).await?;
    println!("Sample data generated successfully!");
    
    // Demo Q API - Querying entities
    println!("\n=== Q API Demo ===");
    
    // Query all platforms
    let platforms = school_service_core::Q::platforms()
        .purpose("Demo: List all platforms")
        .execute_for_list(&_runtime)
        .await?;
    println!("Found {} platform(s):", platforms.len());
    for platform in platforms.iter() {
        println!("  - {} (ID: {})", platform.name(), platform.id());
    }
    
    // Query all school types
    let school_types = school_service_core::Q::school_types()
        .purpose("Demo: List all school types")
        .execute_for_list(&_runtime)
        .await?;
    println!("\nFound {} school type(s):", school_types.len());
    for school_type in school_types.iter() {
        println!("  - {} (Code: {})", school_type.name(), school_type.code());
    }
    
    // Query all schools
    let schools = school_service_core::Q::schools()
        .purpose("Demo: List all schools")
        .execute_for_list(&_runtime)
        .await?;
    println!("\nFound {} school(s):", schools.len());
    for school in schools.iter() {
        println!("  - {} (Address: {})", school.name(), school.address());
    }
    
    // Demo E API - Expression evaluation
    println!("\n=== E API Demo ===");
    
    if let Some(platform) = platforms.first() {
        let platform_expr = school_service_core::E::platform(platform);
        println!("Platform expression: {}", platform_expr.get_name().eval().unwrap_or("N/A".to_string()));
    }
    
    if let Some(school_type) = school_types.first() {
        let school_type_expr = school_service_core::E::school_type(school_type);
        let name = school_type_expr.clone().get_name().eval().unwrap_or("N/A".to_string());
        let code = school_type_expr.get_code().eval().unwrap_or("N/A".to_string());
        println!("School type expression: {} (Code: {})", name, code);
    }
    
    if let Some(school) = schools.first() {
        let school_expr = school_service_core::E::school(school);
        let name = school_expr.clone().get_name().eval().unwrap_or("N/A".to_string());
        let address = school_expr.get_address().eval().unwrap_or("N/A".to_string());
        println!("School expression: {} (Address: {})", name, address);
    }
    
    println!("\n=== Demo Complete ===");
    Ok(())
}
