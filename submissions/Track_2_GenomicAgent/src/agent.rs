use crate::intent;
use crate::llm;
use crate::memory::ConversationMemory;
use crate::tools::ToolRegistry;

/// Minimum BM25 score for a tool to be included in a query's plan.
/// BM25 scores are unbounded (not a [0,1] similarity), and were
/// measured directly against this crate's real 6-tool registry before
/// picking this value: primary/clearly-relevant matches for these
/// tools' actual descriptions land in roughly the 3-18 range, while
/// generic single-shared-word overlap lands under ~1.3. 2.0 sits in the
/// real gap between those two bands for most queries. This is a
/// judgment call, not a solved optimization -- BM25 is term-overlap
/// statistics, not semantic understanding, so it will occasionally
/// include a borderline tool whose description happens to share a
/// generic word (e.g. "SNP") with the query; every included tool's
/// score is shown in the response so that's visible, not hidden.
const INTENT_THRESHOLD: f32 = 2.0;

pub struct GenomicAgent {
    tools: ToolRegistry,
    memory: ConversationMemory,
}

impl GenomicAgent {
    pub fn new(tools: ToolRegistry) -> Self {
        Self { tools, memory: ConversationMemory::new() }
    }

    pub fn memory(&self) -> &ConversationMemory {
        &self.memory
    }

    pub fn clear_memory(&mut self) {
        self.memory.clear();
    }

    /// Plan against a possibly memory-augmented version of the query,
    /// then record the turn. Returns the plan plus a note describing
    /// whether conversation context was applied, so callers can surface
    /// that to the user rather than silently rewriting their question.
    fn plan_with_memory(&self, query: &str) -> (intent::IntentResult, Option<String>) {
        let (effective_query, augmented) = self.memory.augment_query(query);
        let plan = self.plan(&effective_query);
        let note = if augmented {
            Some(format!(
                "[memory] follow-up detected -- planned using context from the previous {} turn(s)",
                self.memory.len().min(2)
            ))
        } else {
            None
        };
        (plan, note)
    }

    /// Short digest of what a turn produced, stored in memory so the
    /// session recap shows something real rather than an opaque entry.
    fn digest(outputs: &[(String, String)]) -> String {
        outputs
            .first()
            .map(|(_, out)| {
                let first_line = out.lines().find(|l| !l.trim().is_empty()).unwrap_or("");
                let mut s: String = first_line.chars().take(90).collect();
                if first_line.chars().count() > 90 {
                    s.push_str("...");
                }
                s
            })
            .unwrap_or_else(|| "(no output)".to_string())
    }

    /// Real, zero-cost, offline planning (see intent.rs -- a custom
    /// GPU-dispatched Okapi BM25 (with bigram features) kernel, not a
    /// transformer, not an external model) decides which tool(s) the
    /// query needs, possibly more than one for a compound question. If
    /// an LLM backend is separately configured and reachable (see
    /// llm.rs), the actual tool output is additionally narrated in
    /// plain English, grounded strictly in numbers already present in
    /// that output. No network call is required for tool selection at
    /// all; only this optional narration step ever touches one, and its
    /// absence never changes which tools ran or what they found.
    pub fn process_query(&mut self, query: &str) -> anyhow::Result<String> {
        let (plan, memory_note) = self.plan_with_memory(query);
        let outputs = self.run_plan(&plan, query)?;

        let mut response = String::new();
        if let Some(note) = &memory_note {
            response.push_str(note);
            response.push('\n');
        }
        response.push_str(&format!(
            "[Intent kernel, {}] Selected tool(s): {}\n",
            plan.compute_path,
            plan.selected
                .iter()
                .map(|m| format!("{} ({:.2})", m.name, m.score))
                .collect::<Vec<_>>()
                .join(", "),
        ));

        let tool_names: Vec<String> = plan.selected.iter().map(|m| m.name.clone()).collect();
        self.memory.remember(query, &tool_names, &Self::digest(&outputs));

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
        let (plan, memory_note) = self.plan_with_memory(query);
        let outputs = self.run_plan(&plan, query)?;

        let mut response = String::new();
        if let Some(note) = &memory_note {
            response.push_str(note);
            response.push('\n');
        }
        response.push_str(&format!(
            "[Intent kernel, {}] Selected tool(s): {}\n",
            plan.compute_path,
            plan.selected
                .iter()
                .map(|m| format!("{} ({:.2})", m.name, m.score))
                .collect::<Vec<_>>()
                .join(", "),
        ));

        let tool_names: Vec<String> = plan.selected.iter().map(|m| m.name.clone()).collect();
        self.memory.remember(query, &tool_names, &Self::digest(&outputs));

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
