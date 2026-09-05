use school_management_service_core::TeaqlEntity;
fn main() {
    let desc = school_management_service_core::SchoolType::entity_descriptor();
    for p in desc.properties {
        println!("Property: {}, is_id: {}, is_version: {}", p.name, p.is_id, p.is_version);
    }
}
