use crate::task_package::TaskPackageData;

/// Build the core system prompt — kept minimal.
/// Only sets the model's role. All domain knowledge comes from context files.
pub fn build_system_prompt() -> String {
    include_str!("../../../prompts/system.txt").to_string()
}

/// Build messages for a lightweight conversational request that must not enter
/// the artifact generation and validation pipeline.
pub fn build_chat_messages(question: &str, model_name: &str) -> Vec<(String, String)> {
    vec![
        (
            "system".to_string(),
            format!(
                "You are Klint, an AI coding agent built by TeaQL for isolated and \
air-gapped development environments. The configured model backend is \
{model_name}. Never claim to be a Xiaomi assistant, MiMo assistant, or a \
product-support bot. Answer the user's question directly and concisely. This \
is a conversational request: do not emit a TeaQL artifact, XML model, plan, \
or validation instructions. If repository changes are required, tell the \
user to submit an explicit development task."
            ),
        ),
        ("user".to_string(), question.to_string()),
    ]
}

/// Build messages for a lightweight intent classification request.
///
/// The model responds with exactly one category word, enabling the TUI
/// to route user input without brittle keyword matching.
pub fn build_classify_intent_messages(input: &str) -> Vec<(String, String)> {
    vec![
        (
            "system".to_string(),
            "You classify user input intent. Respond with exactly one word:\n\
             - TASK: user wants to create, modify, build, fix, generate, refactor, or delete code\n\
             - CHAT: user asks a question, wants an explanation, or makes a conversational request\n\
             - MODEL: user asks about the current model name or configuration\n\
             - ENDPOINT: user asks about the service endpoint or address\n\
             - SERVICE: user asks about service health\n\
             - STATUS: user asks about system or agent status\n\
             Respond with only the category word, nothing else."
                .to_string(),
        ),
        ("user".to_string(), input.to_string()),
    ]
}

/// Load a context file from the prompts directory.
/// Returns None if the file doesn't exist (optional context).
fn load_context_file(path: &str) -> Option<String> {
    std::fs::read_to_string(path).ok()
}

/// Assemble all reference context files into a single block.
/// These are NOT system prompts — they are reference documents
/// loaded from local files and presented as user context.
fn build_context_block(task: &TaskPackageData) -> String {
    let mut parts = Vec::new();

    // Grammar example (from task package)
    if let Some(example) = &task.grammar_example {
        parts.push(format!("## Grammar Example\n\nFollow this structure exactly:\n\n```xml\n{example}\n```"));
    }

    // Value whitelist (from task package)
    if let Some(whitelist) = &task.value_whitelist {
        parts.push(format!("## Allowed Value Forms\n\nUse only these value patterns:\n\n{whitelist}"));
    }

    // Any additional context files from prompts/context.d/ directory
    if let Ok(entries) = std::fs::read_dir("prompts/context.d") {
        let mut files: Vec<_> = entries.flatten()
            .filter(|e| e.path().is_file())
            .collect();
        files.sort_by_key(|e| e.file_name());
        for entry in files {
            if let Ok(content) = std::fs::read_to_string(entry.path()) {
                let name = entry.file_name().to_string_lossy().to_string();
                parts.push(format!("## Context: {name}\n\n{content}"));
            }
        }
    }

    if parts.is_empty() {
        String::new()
    } else {
        format!("# Reference Context\n\nThe following are reference documents loaded from local files.\n\n{}", parts.join("\n\n---\n\n"))
    }
}

/// Build the complete prompt messages for a generation request.
/// Returns Vec of (role, content) pairs.
///
/// Structure:
///   system: minimal role description (from prompts/system.txt)
///   user:   context block (KSML rules + grammar + whitelist) + task
pub fn build_generation_messages(task: &TaskPackageData) -> Vec<(String, String)> {
    let mut messages = vec![("system".to_string(), build_system_prompt())];

    // Build the user message: context block + task + skill
    let context = build_context_block(task);
    let mut user_message = if context.is_empty() {
        task.task_content.clone()
    } else {
        format!("{context}\n\n---\n\n# Task\n\n{}", task.task_content)
    };

    if let Some(skill) = &task.modeling_skill {
        user_message.push_str("\n\n---\n\n# Modeling guidelines (follow these to pass validation on first attempt):\n\n");
        user_message.push_str(skill);
    }

    messages.push(("user".to_string(), user_message));

    messages
}

/// Build the repair prompt messages.
/// This is a FRESH request — not a continuation of the previous conversation.
pub fn build_repair_messages(
    task: &TaskPackageData,
    rejected_candidate: &str,
    actionable_errors: &[String],
    diagnostic_limit: usize,
) -> Vec<(String, String)> {
    let mut messages = vec![("system".to_string(), build_system_prompt())];

    // Same context block for repair
    let context = build_context_block(task);
    let mut user_message = if context.is_empty() {
        task.task_content.clone()
    } else {
        format!("{context}\n\n---\n\n# Task\n\n{}", task.task_content)
    };

    if let Some(skill) = &task.modeling_skill {
        user_message.push_str("\n\n---\n\n# Modeling guidelines:\n\n");
        user_message.push_str(skill);
    }

    messages.push(("user".to_string(), user_message));

    // Rejected candidate
    messages.push(("assistant".to_string(), rejected_candidate.to_string()));

    // Truncated diagnostic with actionable errors only
    let template = include_str!("../../../prompts/repair-domain.txt").to_string();
    let mut errors_str = String::new();
    for err in actionable_errors {
        let truncated: String = err
            .chars()
            .take(diagnostic_limit / actionable_errors.len().max(1))
            .collect();
        errors_str.push_str(&format!("- {truncated}\n"));
    }

    let diagnostic = template.replace("{{errors}}", &errors_str);

    messages.push(("user".to_string(), diagnostic));

    messages
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn chat_prompt_pins_klint_identity_and_disables_artifact_output() {
        let messages = build_chat_messages("Who are you?", "mimo-v2.5-pro");

        assert_eq!(messages.len(), 2);
        assert!(messages[0].1.contains("You are Klint"));
        assert!(messages[0].1.contains("mimo-v2.5-pro"));
        assert!(messages[0].1.contains("do not emit a TeaQL artifact"));
        assert_eq!(
            messages[1],
            ("user".to_string(), "Who are you?".to_string())
        );
    }

    #[test]
    fn generation_prompt_is_an_explicit_teaql_ksml_contract() {
        let prompt = build_system_prompt();

        assert!(prompt.contains("TeaQL KSML"));
        assert!(prompt.contains("exactly one `<root>`"));
        assert!(prompt.contains("Never output GraphQL"));
        assert!(prompt.contains("Output raw XML only"));
        assert!(prompt.contains("<book _name=\"Book\""));
    }

    #[test]
    fn interactive_generation_request_uses_the_teaql_system_contract() {
        let task = TaskPackageData::from_prompt(
            "interactive-task",
            "Build a small library system with about five objects.",
            PathBuf::from("."),
        );

        let messages = build_generation_messages(&task);

        assert_eq!(messages[0].0, "system");
        assert!(messages[0].1.contains("Your only output"));
        assert!(messages[0].1.contains("TeaQL KSML"));
        assert_eq!(messages.last().expect("user message").0, "user");
        assert_eq!(
            messages.last().expect("user message").1,
            "Build a small library system with about five objects."
        );
    }

    #[test]
    fn classify_intent_prompt_enumerates_all_categories() {
        let messages = build_classify_intent_messages("fix input routing");
        assert_eq!(messages.len(), 2);
        assert!(messages[0].1.contains("TASK"));
        assert!(messages[0].1.contains("CHAT"));
        assert!(messages[0].1.contains("MODEL"));
        assert!(messages[0].1.contains("ENDPOINT"));
        assert!(messages[0].1.contains("SERVICE"));
        assert!(messages[0].1.contains("STATUS"));
        assert_eq!(messages[1].1, "fix input routing");
    }
}
