use agent_core::event::ContextBudget;

/// Build a context budget from profile values and estimated prompt size.
pub fn calculate_budget(
    model_context: u32,
    prompt_limit: u32,
    completion_limit: u32,
    safety_reserve: u32,
    estimated_prompt: u32,
) -> ContextBudget {
    ContextBudget {
        model_context,
        prompt_limit,
        completion_limit,
        safety_reserve,
        estimated_prompt,
    }
}

/// Check if a prompt estimate is within budget.
/// Must satisfy: estimated_prompt + completion_limit + safety_reserve <= model_context
pub fn admits(
    model_context: u32,
    completion_limit: u32,
    safety_reserve: u32,
    estimated_prompt: u32,
) -> bool {
    estimated_prompt + completion_limit + safety_reserve <= model_context
}
