use crate::api::RadeonApi;
use crate::tools::ToolRegistry;
use serde_json::Value;
use std::collections::HashMap;

pub struct GenomicAgent {
    api: RadeonApi,
    tools: ToolRegistry,
    #[allow(dead_code)]
    memory: HashMap<String, Value>,
}

impl GenomicAgent {
    pub fn new(api_key: String, tools: ToolRegistry) -> Self {
        Self {
            api: RadeonApi::new(api_key),
            tools,
            memory: HashMap::new(),
        }
    }

    pub async fn process_query(&mut self, query: &str) -> anyhow::Result<String> {
        tracing::info!("Processing query: {}", query);

        let tools_info = self.tools.get_descriptions();
        let prompt = self.build_system_prompt(&tools_info);

        let response = self.api.call_llm(&prompt, query).await?;

        if let Some(tool_name) = self.extract_tool_call(&response) {
            tracing::info!("Tool selected: {}", tool_name);
            let tool_result = self.tools.execute(&tool_name, query).await?;

            let refinement_prompt = format!(
                "Based on this query: '{}'\n\nTool result:\n{}\n\nProvide a concise, human-friendly summary.",
                query, tool_result
            );

            let final_response = self.api.call_llm(&prompt, &refinement_prompt).await?;
            Ok(final_response)
        } else {
            Ok(response)
        }
    }

    fn build_system_prompt(&self, tools: &[String]) -> String {
        format!(
            "You are a genomics research assistant. You have access to these tools:\n\n{}\n\n\
             Analyze user queries and recommend the appropriate tool. Be concise and technical.",
            tools.join("\n")
        )
    }

    fn extract_tool_call(&self, response: &str) -> Option<String> {
        for tool_desc in self.tools.get_descriptions() {
            let tool_name = tool_desc.split('\n').next().unwrap_or("");
            if response.contains(tool_name) {
                return Some(tool_name.to_string());
            }
        }
        None
    }
}
