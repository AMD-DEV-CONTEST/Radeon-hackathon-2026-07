use crate::tools::ToolRegistry;

pub struct GenomicAgent {
    tools: ToolRegistry,
}

impl GenomicAgent {
    pub fn new(tools: ToolRegistry) -> Self {
        Self { tools }
    }

    pub fn process_query(&mut self, query: &str) -> anyhow::Result<String> {
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
        if query.contains("VCF") || query.contains("SNP") {
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
