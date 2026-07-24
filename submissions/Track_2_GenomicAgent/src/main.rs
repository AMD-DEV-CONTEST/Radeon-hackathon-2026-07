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
mod knowledge;
mod memory;
mod rng;
#[cfg(feature = "local-inference")]
mod local_llm;

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

    if args.len() > 1 && args[1] == "chat" {
        chat_mode()?;
        return Ok(());
    }

    if args.len() > 1 && args[1] == "conversation" {
        conversation_demo()?;
        return Ok(());
    }

    #[cfg(feature = "local-inference")]
    if args.len() > 1 && args[1] == "local-bench" {
        local_llm::run_local_bench()?;
        return Ok(());
    }

    let mut registry = ToolRegistry::new();
    registry.register(Box::new(tools::VcfAnalyzerTool));
    registry.register(Box::new(tools::LdBlockTool));
    registry.register(Box::new(tools::HaplotypeToolTool));
    registry.register(Box::new(tools::PopulationStructureTool));
    registry.register(Box::new(tools::LdConfidenceTool));
    registry.register(Box::new(tools::SelectionScanTool));
    registry.register(Box::new(tools::KnowledgeLookupTool));

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
    registry.register(Box::new(tools::KnowledgeLookupTool));

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

fn build_registry() -> ToolRegistry {
    let mut registry = ToolRegistry::new();
    registry.register(Box::new(tools::VcfAnalyzerTool));
    registry.register(Box::new(tools::LdBlockTool));
    registry.register(Box::new(tools::HaplotypeToolTool));
    registry.register(Box::new(tools::PopulationStructureTool));
    registry.register(Box::new(tools::LdConfidenceTool));
    registry.register(Box::new(tools::SelectionScanTool));
    registry.register(Box::new(tools::KnowledgeLookupTool));
    registry
}

/// Scripted multi-turn conversation -- the non-interactive counterpart
/// to `chat`, so the multi-turn memory and local RAG behaviour can be
/// demonstrated in a recording or a CI run without typing.
///
/// Turns 3 and 5 are deliberately short referential follow-ups ("and
/// its p-value?") that carry almost no topical terms of their own: they
/// only route correctly because conversation memory supplies the
/// missing context. That contrast is the point of the demo.
fn conversation_demo() -> anyhow::Result<()> {
    let mut agent = GenomicAgent::new(build_registry());

    let turns = vec![
        "Run a selection scan for FST differentiation between ancestry clusters",
        "What does the fixation index FST actually measure?",
        "and its p-value?",
        "What are the linkage disequilibrium blocks in this region?",
        "why does that matter?",
    ];

    println!("=== Multi-turn conversation demo (local memory + local RAG) ===\n");
    for (i, turn) in turns.iter().enumerate() {
        println!("--------------------------------------------------------------");
        println!("Turn {}: {}", i + 1, turn);
        println!("--------------------------------------------------------------");
        let response = agent.process_query_offline(turn)?;
        // Head of the response: the routing line, memory note, and the
        // start of the first tool's real output.
        for line in response.lines().take(14) {
            println!("{line}");
        }
        println!();
    }

    println!("=== Session memory recap ===");
    print!("{}", agent.memory().summary());
    Ok(())
}

/// Interactive multi-turn chat. Everything stays in-process: routing is
/// the offline GPU BM25 kernel, retrieval is the local corpus, and
/// memory is never persisted to disk or sent anywhere.
fn chat_mode() -> anyhow::Result<()> {
    use std::io::{self, BufRead, Write};

    let mut agent = GenomicAgent::new(build_registry());

    println!("Genomic Research Agent -- interactive multi-turn session.");
    println!("Everything runs locally: no API key, no network call.");
    println!("Commands: 'memory' (show what's remembered), 'forget' (clear), 'exit'.\n");

    let stdin = io::stdin();
    loop {
        print!("> ");
        io::stdout().flush().ok();

        let mut line = String::new();
        if stdin.lock().read_line(&mut line)? == 0 {
            break; // EOF (piped input ended)
        }
        let query = line.trim();

        match query {
            "" => continue,
            "exit" | "quit" => break,
            "memory" => {
                print!("{}", agent.memory().summary());
                continue;
            }
            "forget" => {
                agent.clear_memory();
                println!("(memory cleared)");
                continue;
            }
            _ => {}
        }

        match agent.process_query_offline(query) {
            Ok(response) => println!("{response}"),
            Err(e) => println!("error: {e}"),
        }
    }

    println!("\nSession ended. {} turn(s) were remembered.", agent.memory().len());
    Ok(())
}
