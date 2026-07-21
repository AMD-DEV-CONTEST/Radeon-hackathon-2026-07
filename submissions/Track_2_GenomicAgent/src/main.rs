mod agent;
mod tools;
mod bench;
mod vcf;
mod gpu_ld;
mod pca;
mod llm;
mod bootstrap;
mod fst;
mod intent;

use agent::GenomicAgent;
use tools::ToolRegistry;
use std::env;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = env::args().collect();

    if args.len() > 1 && args[1] == "bench" {
        bench::run_benchmarks()?;
        return Ok(());
    }

    if args.len() > 1 && args[1] == "gpu-bench" {
        bench::run_gpu_benchmark()?;
        return Ok(());
    }

    if args.len() > 1 && args[1] == "fast" {
        fast_mode()?;
        return Ok(());
    }

    let mut registry = ToolRegistry::new();
    registry.register(Box::new(tools::VcfAnalyzerTool));
    registry.register(Box::new(tools::LdBlockTool));
    registry.register(Box::new(tools::HaplotypeToolTool));
    registry.register(Box::new(tools::PopulationStructureTool));
    registry.register(Box::new(tools::LdConfidenceTool));
    registry.register(Box::new(tools::SelectionScanTool));

    let mut agent = GenomicAgent::new(registry);

    let queries = vec![
        "Analyze the VCF file and tell me about SNP distribution",
        "What are the linkage disequilibrium blocks in this region?",
        "Find haplotype patterns for variants with MAF > 0.05",
        "Run population structure PCA to check for ancestry clustering",
        "How confident are we in the strongest LD estimate -- give a bootstrap confidence interval",
        "Run a selection scan for FST differentiation between ancestry clusters",
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

fn fast_mode() -> anyhow::Result<()> {
    let mut registry = ToolRegistry::new();
    registry.register(Box::new(tools::VcfAnalyzerTool));
    registry.register(Box::new(tools::LdBlockTool));
    registry.register(Box::new(tools::HaplotypeToolTool));
    registry.register(Box::new(tools::PopulationStructureTool));
    registry.register(Box::new(tools::LdConfidenceTool));
    registry.register(Box::new(tools::SelectionScanTool));

    let mut agent = GenomicAgent::new(registry);

    let queries = vec![
        "Analyze the VCF file and tell me about SNP distribution",
        "What are the linkage disequilibrium blocks in this region?",
        "Find haplotype patterns for variants with MAF > 0.05",
        "Run population structure PCA to check for ancestry clustering",
        "How confident are we in the strongest LD estimate -- give a bootstrap confidence interval",
        "Run a selection scan for FST differentiation between ancestry clusters",
    ];

    let n = queries.len();
    for query in queries {
        let _response = agent.process_query_offline(query)?;
    }

    println!("✓ {n} queries processed in ultra-fast mode");
    Ok(())
}
