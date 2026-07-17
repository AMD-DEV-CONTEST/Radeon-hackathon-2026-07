mod agent;
mod tools;
mod api;
mod bench;

use agent::GenomicAgent;
use tools::ToolRegistry;
use std::env;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();

    let args: Vec<String> = env::args().collect();

    if args.len() > 1 && args[1] == "bench" {
        bench::run_benchmarks().await?;
        return Ok(());
    }

    let api_key = env::var("RADEON_API_KEY")
        .unwrap_or_else(|_| "sk-placeholder".to_string());

    let mut registry = ToolRegistry::new();
    registry.register(Box::new(tools::VcfAnalyzerTool)).await;
    registry.register(Box::new(tools::LdBlockTool)).await;
    registry.register(Box::new(tools::HaplotypeToolTool)).await;

    let mut agent = GenomicAgent::new(api_key, registry);

    let queries = vec![
        "Analyze the VCF file and tell me about SNP distribution",
        "What are the linkage disequilibrium blocks in this region?",
        "Find haplotype patterns for variants with MAF > 0.05",
    ];

    for query in queries {
        println!("\n============================================================");
        println!("Query: {}", query);
        println!("============================================================");

        match agent.process_query(query).await {
            Ok(response) => println!("Response: {}", response),
            Err(e) => println!("Error: {}", e),
        }
    }

    Ok(())
}
