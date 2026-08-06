use school_service_core::*;
use school_service_core::teaql_core::Entity;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("[{}] Starting School Management System...", chrono::Local::now().format("%Y-%m-%d %H:%M:%S%.3f"));
    
    // Initialize runtime
    let ctx = school_service_core::service_runtime_from_env().await?;
    ctx.ensure_schema().await?;
    
    println!("✅ Database schema initialized successfully");
    
    // Test Q API - Query Platform
    println!("\n🔍 Testing Q API - Query Platform:");
    let platforms = Q::platforms().purpose("Query all platforms").execute_for_list(&ctx).await?;
    println!("Found {} platforms", platforms.len());
    
    if platforms.is_empty() {
        println!("Creating default platform...");
        let mut new_platform = Q::platforms().purpose("Create platform").new_entity(&ctx);
        new_platform.update_name("School Management Platform".to_string());
        new_platform.update_description("A comprehensive platform for managing schools".to_string());
        new_platform.audit_as("Initial setup").save(&ctx).await?;
        println!("✅ Platform created successfully");
    }
    
    // Test Q API - Query School Types
    println!("\n🔍 Testing Q API - Query School Types:");
    let school_types = Q::school_types().purpose("Query all school types").execute_for_list(&ctx).await?;
    println!("Found {} school types", school_types.len());
    
    for school_type in &school_types {
        println!("  - {}: {}", school_type.code(), school_type.name());
    }
    
    // Test Q API - Query Schools
    println!("\n🔍 Testing Q API - Query Schools:");
    let schools = Q::schools().purpose("Query all schools").execute_for_list(&ctx).await?;
    println!("Found {} schools", schools.len());
    
    // Test E API - Expression for Platform
    println!("\n🔍 Testing E API - Expression for Platform:");
    if let Some(platform) = platforms.first() {
        let platform_name = E::platform(platform).get_name().unwrap();
        println!("Platform name: {}", platform_name);
    }
    
    // Test E API - Expression for School
    println!("\n🔍 Testing E API - Expression for School:");
    if let Some(school) = schools.first() {
        let school_name = E::school(school).get_name().unwrap();
        let school_address = E::school(school).get_address().unwrap();
        println!("School: {} at {}", school_name, school_address);
    }
    
    // Test Create API - Create a new school
    println!("\n🔍 Testing Create API - Create a new school:");
    if let Some(platform) = platforms.first() {
        let mut new_school = Q::schools().purpose("Create school").new_entity(&ctx);
        new_school.update_name("New Test School".to_string());
        new_school.update_address("456 Learning Street".to_string());
        new_school.update_established_year(2020);
        new_school.update_platform_id(platform.id());
        new_school.update_school_type_to_primary();
        new_school.audit_as("Test school creation").save(&ctx).await?;
        println!("✅ School created successfully");
        
        // Query again to verify
        let updated_schools = Q::schools().purpose("Verify school creation").execute_for_list(&ctx).await?;
        println!("Total schools after creation: {}", updated_schools.len());
    }
    
    println!("\n✅ All API tests completed successfully!");
    println!("📊 Summary:");
    println!("  - Q API (Query): Tested for Platform, SchoolType, and School");
    println!("  - E API (Expression): Tested for Platform and School");
    println!("  - Create API: Tested for School");
    
    Ok(())
}