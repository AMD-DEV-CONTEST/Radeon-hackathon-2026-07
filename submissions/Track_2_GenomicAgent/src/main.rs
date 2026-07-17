mod agent;
mod tools;
mod bench;

use agent::GenomicAgent;
use tools::ToolRegistry;
use std::env;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = env::args().collect();

    if args.len() > 1 && args[1] == "bench" {
        bench::run_benchmarks()?;
        return Ok(());
    }

    let mut registry = ToolRegistry::new();
    registry.register(Box::new(tools::VcfAnalyzerTool));
    registry.register(Box::new(tools::LdBlockTool));
    registry.register(Box::new(tools::HaplotypeToolTool));

    let mut agent = GenomicAgent::new(registry);

    let queries = vec![
        "Analyze the VCF file and tell me about SNP distribution",
        "What are the linkage disequilibrium blocks in this region?",
        "Find haplotype patterns for variants with MAF > 0.05",
    ];

    for query in queries {
        println!("\n============================================================");
        println!("Query: {}", query);
        println!("============================================================");

        match agent.process_query(query) {
            Ok(response) => println!("Response: {}", response),
            Err(e) => println!("Error: {}", e),
        }
    }

    Ok(())
}
