use crate::intent;
use crate::llm;
use crate::tools::ToolRegistry;

/// Minimum cosine similarity for a tool to be included in a query's
/// plan. Chosen empirically against this crate's own tool descriptions
/// (see intent.rs tests) -- low enough that a compound query pulls in
/// every genuinely relevant tool, high enough that unrelated tools
/// don't get dragged in by a single shared word.
const INTENT_THRESHOLD: f32 = 0.15;

pub struct GenomicAgent {
    tools: ToolRegistry,
}

impl GenomicAgent {
    pub fn new(tools: ToolRegistry) -> Self {
        Self { tools }
    }

    /// Real, zero-cost, offline planning (see intent.rs -- a custom
    /// GPU-dispatched TF-IDF/cosine-similarity kernel, not a
    /// transformer, not an external model) decides which tool(s) the
    /// query needs, possibly more than one for a compound question. If
    /// an LLM backend is separately configured and reachable (see
    /// llm.rs), the actual tool output is additionally narrated in
    /// plain English, grounded strictly in numbers already present in
    /// that output. No network call is required for tool selection at
    /// all; only this optional narration step ever touches one, and its
    /// absence never changes which tools ran or what they found.
    pub fn process_query(&mut self, query: &str) -> anyhow::Result<String> {
        let plan = self.plan(query);
        let outputs = self.run_plan(&plan, query)?;

        let mut response = format!(
            "[Intent kernel, {}] Selected tool(s): {}\n",
            plan.compute_path,
            plan.selected
                .iter()
                .map(|m| format!("{} ({:.2})", m.name, m.score))
                .collect::<Vec<_>>()
                .join(", "),
        );

        match llm::synthesize(query, &outputs) {
            Some(narrative) => response.push_str(&format!("\nAnalyst summary: {narrative}\n")),
            None => response.push_str("\n(No LLM narration configured/available this run -- showing raw tool output.)\n"),
        }
        for (name, output) in &outputs {
            response.push_str(&format!("\n--- {name} raw output ---\n{output}\n"));
        }

        Ok(response)
    }

    /// Same real planning as `process_query`, but never attempts an LLM
    /// narration call. Used by `--fast` mode (measuring this crate's own
    /// per-query overhead, not third-party API latency) and as the pure
    /// zero-network path in general -- tool selection quality is
    /// identical either way, since planning never depended on a network
    /// call to begin with.
    pub fn process_query_offline(&mut self, query: &str) -> anyhow::Result<String> {
        let plan = self.plan(query);
        let outputs = self.run_plan(&plan, query)?;

        let mut response = format!(
            "[Intent kernel, {}] Selected tool(s): {}\n",
            plan.compute_path,
            plan.selected
                .iter()
                .map(|m| format!("{} ({:.2})", m.name, m.score))
                .collect::<Vec<_>>()
                .join(", "),
        );
        for (name, output) in &outputs {
            response.push_str(&format!("\n--- {name} raw output ---\n{output}\n"));
        }

        Ok(response)
    }

    fn plan(&self, query: &str) -> intent::IntentResult {
        let tools_info = self.tools.get_descriptions();
        let mut names = Vec::with_capacity(tools_info.len());
        let mut descriptions = Vec::with_capacity(tools_info.len());
        for d in &tools_info {
            if let Some((name, desc)) = d.split_once(':') {
                names.push(name.trim().to_string());
                descriptions.push(desc.trim().to_string());
            }
        }
        intent::classify(query, &names, &descriptions, INTENT_THRESHOLD)
    }

    fn run_plan(&self, plan: &intent::IntentResult, query: &str) -> anyhow::Result<Vec<(String, String)>> {
        let mut outputs = Vec::with_capacity(plan.selected.len());
        for m in &plan.selected {
            let result = self.tools.execute(&m.name, query)?;
            outputs.push((m.name.clone(), result));
        }
        Ok(outputs)
    }
}
