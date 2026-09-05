use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Run summary for the final report.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunSummary {
    pub run_id: String,
    pub task_name: String,
    pub model: String,
    pub profile: String,
    pub started_at: DateTime<Utc>,
    pub completed_at: DateTime<Utc>,
    pub final_status: String,
    pub pass_at_1: bool,
    pub pass_after_repair: bool,
    pub total_attempts: u8,
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
    pub total_elapsed_secs: f64,
    pub stage_timings: Vec<StageSummary>,
    pub validation_results: Vec<ValidationSummary>,
    pub candidate_hash: Option<String>,
    pub final_hash: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StageSummary {
    pub stage: String,
    pub elapsed_secs: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationSummary {
    pub level: u8,
    pub level_name: String,
    pub passed: bool,
    pub error_count: u32,
    pub warning_count: u32,
}

/// Format a run summary as Markdown report.
pub fn format_markdown_report(summary: &RunSummary) -> String {
    let mut md = String::new();
    md.push_str(&format!("# Run Report: {}\n\n", summary.run_id));
    md.push_str(&format!("**Task:** {}\n\n", summary.task_name));
    md.push_str(&format!(
        "**Model:** {} (profile: {})\n\n",
        summary.model, summary.profile
    ));
    md.push_str(&format!("**Status:** {}\n\n", summary.final_status));
    md.push_str(&format!(
        "**Pass@1:** {}\n\n",
        if summary.pass_at_1 { "✓" } else { "✗" }
    ));
    md.push_str(&format!(
        "**Pass after repair:** {}\n\n",
        if summary.pass_after_repair {
            "✓"
        } else {
            "✗"
        }
    ));
    md.push_str(&format!("**Attempts:** {}\n\n", summary.total_attempts));

    md.push_str("## Tokens\n\n");
    md.push_str(&format!("| Metric | Value |\n|--------|-------|\n"));
    md.push_str(&format!("| Prompt | {} |\n", summary.prompt_tokens));
    md.push_str(&format!("| Completion | {} |\n", summary.completion_tokens));
    md.push_str(&format!(
        "| Total time | {:.1}s |\n\n",
        summary.total_elapsed_secs
    ));

    md.push_str("## Pipeline\n\n");
    md.push_str("| Stage | Time |\n|-------|------|\n");
    for stage in &summary.stage_timings {
        md.push_str(&format!(
            "| {} | {:.1}s |\n",
            stage.stage, stage.elapsed_secs
        ));
    }
    md.push_str("\n");

    md.push_str("## Validation\n\n");
    md.push_str("| Level | Name | Status | Errors | Warnings |\n");
    md.push_str("|-------|------|--------|--------|----------|\n");
    for v in &summary.validation_results {
        let status = if v.passed { "✓" } else { "✗" };
        md.push_str(&format!(
            "| L{} | {} | {} | {} | {} |\n",
            v.level, v.level_name, status, v.error_count, v.warning_count
        ));
    }

    md
}
