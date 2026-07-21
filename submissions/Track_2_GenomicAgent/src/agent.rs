use crate::llm;
use crate::tools::ToolRegistry;

pub struct GenomicAgent {
    tools: ToolRegistry,
}

impl GenomicAgent {
    pub fn new(tools: ToolRegistry) -> Self {
        Self { tools }
    }

    /// Real multi-step planning + synthesis when `ANTHROPIC_API_KEY` is
    /// set and reachable (see `llm.rs`): the model picks which
    /// registered tool(s) the query needs -- possibly more than one --
    /// runs them, and narrates the actual results. Falls back to
    /// `process_query_offline` unchanged if the LLM path returns nothing
    /// usable (no key, no network, bad response).
    pub fn process_query(&mut self, query: &str) -> anyhow::Result<String> {
        let tools_info = self.tools.get_descriptions();

        let Some(tool_names) = llm::plan(query, &tools_info) else {
            return self.process_query_offline(query);
        };

        let mut outputs = Vec::with_capacity(tool_names.len());
        for name in &tool_names {
            let result = self.tools.execute(name, query)?;
            outputs.push((name.clone(), result));
        }

        let mut response = format!("[LLM-planned] Selected tool(s): {}\n", tool_names.join(", "));
        match llm::synthesize(query, &outputs) {
            Some(narrative) => response.push_str(&format!("\nAnalyst summary: {narrative}\n")),
            None => response.push_str("\n(LLM synthesis unavailable this run -- showing raw tool output.)\n"),
        }
        for (name, output) in &outputs {
            response.push_str(&format!("\n--- {name} raw output ---\n{output}\n"));
        }

        Ok(response)
    }

    /// Deterministic path: no network calls, ever. This is what
    /// `--fast` mode uses, since that mode is measuring this crate's own
    /// per-query overhead, not third-party API latency, and it's the
    /// fallback `process_query` uses when the LLM path isn't available.
    pub fn process_query_offline(&mut self, query: &str) -> anyhow::Result<String> {
        let tools_info = self.tools.get_descriptions();
        let response = self.route_to_tool(&tools_info, query);

        if let Some(tool_name) = self.extract_tool_call(&response) {
            let tool_result = self.tools.execute(&tool_name, query)?;
            Ok(format!("{}\n\nResult: {}", response, tool_result))
        } else {
            Ok(response)
        }
    }

    fn route_to_tool(&self, _tools: &[String], query: &str) -> String {
        if query.contains("confiden") || query.contains("bootstrap") || query.contains("certain") || query.contains("reliable") {
            "Using LdConfidence tool (GPU-batched bootstrap) to quantify estimate uncertainty.".to_string()
        } else if query.contains("population") || query.contains("ancestry") || query.contains("PCA") || query.contains("structure") {
            "Using PopulationStructure tool (GPU-accelerated PCA) to analyze ancestry patterns.".to_string()
        } else if query.contains("VCF") || query.contains("SNP") {
            "Using VcfAnalyzer tool to examine variant distributions.".to_string()
        } else if query.contains("linkage") || query.contains("LD") {
            "Using LdBlock tool to identify LD patterns.".to_string()
        } else if query.contains("haplotype") {
            "Using HaplotypeTool to analyze allele patterns.".to_string()
        } else {
            "Using VcfAnalyzer for genomic analysis.".to_string()
        }
    }

    fn extract_tool_call(&self, response: &str) -> Option<String> {
        for tool_desc in self.tools.get_descriptions() {
            let tool_name = tool_desc.split(':').next().unwrap_or("");
            if response.contains(tool_name) {
                return Some(tool_name.to_string());
            }
        }
        None
    }
}
