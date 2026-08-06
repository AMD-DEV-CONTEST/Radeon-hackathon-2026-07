
//! Test file demonstrating Q and E API usage for the School Management System

use school_service_core::*;
use teaql_core::Entity;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("=== School Management System - Q and E API Demo ===\n");
    
    // Create runtime
    let runtime = service_runtime_from_env().await?;
    runtime.ensure_schema().await?;
    
    // Generate sample data
    println!("Generating sample data...");
    sample_data::generate_sample_data(&runtime, sample_data::SampleDataPlan::small()).await?;
    println!("Sample data generated successfully!\n");
    
    // Demo Q API - Querying entities
    println!("=== Q API Demo ===");
    
    // Query all platforms
    let platforms = Q::platforms()
        .execute(&runtime)
        .await?;
    println!("Found {} platform(s):", platforms.len());
    for platform in &platforms {
        println!("  - {} (ID: {})", platform.name(), platform.id());
    }
    
    // Query all school types
    let school_types = Q::school_types()
        .execute(&runtime)
        .await?;
    println!("\nFound {} school type(s):", school_types.len());
    for school_type in &school_types {
        println!("  - {} (Code: {})", school_type.name(), school_type.code());
    }
    
    // Query all schools
    let schools = Q::schools()
        .execute(&runtime)
        .await?;
    println!("\nFound {} school(s):", schools.len());
    for school in &schools {
        println!("  - {} (Address: {})", school.name(), school.address());
    }
    
    // Demo E API - Expression evaluation
    println!("\n=== E API Demo ===");
    
    if let Some(platform) = platforms.first() {
        let platform_expr = E::platform(platform);
        println!("Platform expression: {}", platform_expr.name());
    }
    
    if let Some(school_type) = school_types.first() {
        let school_type_expr = E::school_type(school_type);
        println!("School type expression: {} (Code: {})", 
                 school_type_expr.name(), 
                 school_type_expr.code());
    }
    
    if let Some(school) = schools.first() {
        let school_expr = E::school(school);
        println!("School expression: {} (Address: {})", 
                 school_expr.name(), 
                 school_expr.address());
    }
    
    println!("\n=== Demo Complete ===");
    Ok(())
}
