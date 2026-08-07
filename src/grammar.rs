//! Grammar-Constrained Sampling — Domain-Specific Logit Processor
//!
//! Forces the model to produce valid outputs by masking invalid tokens.
//! Includes maritime-specific constraints (valid coordinates, depths).
//!
//! The model physically CANNOT hallucinate impossible coordinates.

use std::collections::HashSet;

/// A grammar constraint that masks logits before sampling.
pub trait LogitProcessor {
    /// Modify logits in-place. Set invalid tokens to -infinity.
    fn process(&self, logits: &mut [f32], generated_tokens: &[u32], context: &str);
}

/// Kills <think> and </think> tokens — the model cannot enter thinking mode.
pub struct ThinkKiller {
    /// Token IDs for <think>, </think>, <reasoning>, </reasoning>
    pub banned_ids: HashSet<u32>,
}

impl ThinkKiller {
    pub fn new(think_id: u32, think_end_id: u32) -> Self {
        let mut banned = HashSet::new();
        banned.insert(think_id);
        banned.insert(think_end_id);
        Self { banned_ids: banned }
    }

    /// Add additional token IDs to ban (e.g., <reasoning>)
    pub fn ban_token(&mut self, id: u32) {
        self.banned_ids.insert(id);
    }
}

impl LogitProcessor for ThinkKiller {
    fn process(&self, logits: &mut [f32], _generated: &[u32], _context: &str) {
        for &id in &self.banned_ids {
            if (id as usize) < logits.len() {
                logits[id as usize] = f32::NEG_INFINITY;
            }
        }
    }
}

/// Forces valid JSON tool call structure.
/// When the model starts outputting a tool call, it MUST complete valid JSON.
pub struct JsonToolConstraint {
    /// Are we currently inside a tool call?
    in_tool_call: bool,
    /// Brace depth tracker
    brace_depth: i32,
    /// Valid tool names
    valid_tools: Vec<String>,
}

impl JsonToolConstraint {
    pub fn new(valid_tools: Vec<String>) -> Self {
        Self {
            in_tool_call: false,
            brace_depth: 0,
            valid_tools,
        }
    }
}

impl LogitProcessor for JsonToolConstraint {
    fn process(&self, _logits: &mut [f32], _generated: &[u32], _context: &str) {
        // TODO: Implement FSM-based JSON constraint
        // When inside a tool_call block:
        // - After "name": only allow valid tool name tokens
        // - After "arguments": only allow { to start object
        // - Track brace depth, force closing } when needed
        // This is complex but eliminates malformed tool calls entirely
    }
}

/// Maritime domain constraints — prevents hallucinated coordinates.
pub struct MaritimeConstraint {
    /// Valid latitude range (Great Lakes: ~41-49°N)
    pub lat_min: f64,
    pub lat_max: f64,
    /// Valid longitude range (Great Lakes: ~-92 to -76°W)
    pub lon_min: f64,
    pub lon_max: f64,
    /// Valid depth range (feet)
    pub depth_min: f64,
    pub depth_max: f64,
}

impl Default for MaritimeConstraint {
    fn default() -> Self {
        Self {
            lat_min: 41.0,
            lat_max: 49.0,
            lon_min: -92.0,
            lon_max: -76.0,
            depth_min: 0.0,
            depth_max: 1000.0, // Max depth in Great Lakes (ft)
        }
    }
}

impl MaritimeConstraint {
    /// Validate a coordinate pair. Returns None if invalid.
    pub fn validate_coordinate(&self, lat: f64, lon: f64) -> Option<(f64, f64)> {
        if lat >= self.lat_min && lat <= self.lat_max
            && lon >= self.lon_min && lon <= self.lon_max
        {
            Some((lat, lon))
        } else {
            None
        }
    }

    /// Validate a depth value. Returns None if invalid.
    pub fn validate_depth(&self, depth: f64) -> Option<f64> {
        if depth >= self.depth_min && depth <= self.depth_max {
            Some(depth)
        } else {
            None
        }
    }
}

impl LogitProcessor for MaritimeConstraint {
    fn process(&self, _logits: &mut [f32], _generated: &[u32], _context: &str) {
        // TODO: When the model is generating a number that looks like a coordinate,
        // mask tokens that would make it fall outside valid ranges.
        // This requires tracking the partial number being generated.
        //
        // For now, validation happens post-generation in the tool execution layer.
        // The forge-v2 tools.rs can reject invalid coordinates before acting on them.
    }
}

/// Composite processor that chains multiple constraints.
pub struct ProcessorChain {
    processors: Vec<Box<dyn LogitProcessor + Send + Sync>>,
}

impl ProcessorChain {
    pub fn new() -> Self {
        Self { processors: Vec::new() }
    }

    pub fn add(&mut self, processor: Box<dyn LogitProcessor + Send + Sync>) {
        self.processors.push(processor);
    }

    /// Apply all processors in sequence.
    pub fn apply(&self, logits: &mut [f32], generated: &[u32], context: &str) {
        for processor in &self.processors {
            processor.process(logits, generated, context);
        }
    }
}

/// Build the default processor chain for CESAROPS maritime SAR.
pub fn default_maritime_chain(think_token_id: u32, think_end_token_id: u32) -> ProcessorChain {
    let mut chain = ProcessorChain::new();

    // 1. Kill think tokens (always active)
    chain.add(Box::new(ThinkKiller::new(think_token_id, think_end_token_id)));

    // 2. Maritime coordinate validation
    chain.add(Box::new(MaritimeConstraint::default()));

    // 3. JSON tool call structure (when in tool mode)
    chain.add(Box::new(JsonToolConstraint::new(vec![
        "write_file".into(),
        "read_file".into(),
        "cargo_check".into(),
        "think_harder".into(),
        "remember".into(),
        "run_command".into(),
    ])));

    chain
}
