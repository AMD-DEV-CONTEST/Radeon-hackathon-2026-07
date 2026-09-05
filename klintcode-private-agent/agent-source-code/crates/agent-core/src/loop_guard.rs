use crate::chat::ChatMessage;
use std::collections::VecDeque;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

/// Detected loop pattern
#[derive(Debug, Clone)]
pub enum LoopDetection {
    /// Same tool called with identical args producing identical output, N times consecutively
    ToolRepeat {
        tool_name: String,
        consecutive_count: usize,
    },
    /// Identical prompt sent to the model N times consecutively
    PromptRepeat { consecutive_count: usize },
}

impl LoopDetection {
    pub fn consecutive_count(&self) -> usize {
        match self {
            LoopDetection::ToolRepeat {
                consecutive_count, ..
            } => *consecutive_count,
            LoopDetection::PromptRepeat {
                consecutive_count, ..
            } => *consecutive_count,
        }
    }
}

impl std::fmt::Display for LoopDetection {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LoopDetection::ToolRepeat {
                tool_name,
                consecutive_count,
            } => {
                write!(f, "ToolRepeat({}, {}x)", tool_name, consecutive_count)
            }
            LoopDetection::PromptRepeat { consecutive_count } => {
                write!(f, "PromptRepeat({}x)", consecutive_count)
            }
        }
    }
}

/// Fingerprint of a single tool call (name+args hash, output hash)
#[derive(Debug, Clone, PartialEq, Eq)]
struct ToolFingerprint {
    name: String,
    name_args_hash: u64,
    output_hash: u64,
}

/// Loop detection guard that tracks recent tool calls and prompts
/// to identify repetitive patterns indicating the agent is stuck.
pub struct LoopGuard {
    recent_tool_calls: VecDeque<ToolFingerprint>,
    recent_prompt_hashes: VecDeque<u64>,
    threshold: usize,
}

impl LoopGuard {
    pub fn new(threshold: usize) -> Self {
        let threshold = threshold.max(2); // minimum 2 to avoid false positives
        Self {
            recent_tool_calls: VecDeque::with_capacity(threshold + 1),
            recent_prompt_hashes: VecDeque::with_capacity(threshold + 1),
            threshold,
        }
    }

    /// Record a tool call. Returns `Some(LoopDetection)` if the last `threshold`
    /// calls are all identical (same tool name, same args, same output).
    pub fn record_tool_call(
        &mut self,
        name: &str,
        args: &str,
        output: &str,
    ) -> Option<LoopDetection> {
        let fp = ToolFingerprint {
            name: name.to_string(),
            name_args_hash: hash_pair(name, args),
            output_hash: hash_str(output),
        };

        self.recent_tool_calls.push_back(fp);
        if self.recent_tool_calls.len() > self.threshold {
            self.recent_tool_calls.pop_front();
        }

        // Check if all entries in the window are identical
        if self.recent_tool_calls.len() >= self.threshold {
            let reference = &self.recent_tool_calls[self.recent_tool_calls.len() - 1];
            let all_same = self
                .recent_tool_calls
                .iter()
                .rev()
                .take(self.threshold)
                .all(|fp| fp == reference);

            if all_same {
                return Some(LoopDetection::ToolRepeat {
                    tool_name: reference.name.clone(),
                    consecutive_count: self.threshold,
                });
            }
        }

        None
    }

    /// Record a prompt (the full message list sent to the model).
    /// Returns `Some(LoopDetection)` if the last `threshold` prompts are identical.
    pub fn record_prompt(&mut self, messages: &[ChatMessage]) -> Option<LoopDetection> {
        let h = hash_messages(messages);

        self.recent_prompt_hashes.push_back(h);
        if self.recent_prompt_hashes.len() > self.threshold {
            self.recent_prompt_hashes.pop_front();
        }

        if self.recent_prompt_hashes.len() >= self.threshold {
            let reference = self.recent_prompt_hashes[self.recent_prompt_hashes.len() - 1];
            let all_same = self
                .recent_prompt_hashes
                .iter()
                .rev()
                .take(self.threshold)
                .all(|&h| h == reference);

            if all_same {
                return Some(LoopDetection::PromptRepeat {
                    consecutive_count: self.threshold,
                });
            }
        }

        None
    }

    /// Reset internal state (e.g. after a successful intervention breaks the loop)
    pub fn reset(&mut self) {
        self.recent_tool_calls.clear();
        self.recent_prompt_hashes.clear();
    }
}

fn hash_str(s: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    s.hash(&mut hasher);
    hasher.finish()
}

fn hash_pair(a: &str, b: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    a.hash(&mut hasher);
    b.hash(&mut hasher);
    hasher.finish()
}

fn hash_messages(messages: &[ChatMessage]) -> u64 {
    let mut hasher = DefaultHasher::new();
    for m in messages {
        m.role.hash(&mut hasher);
        if let Some(ref content) = m.content {
            content.hash(&mut hasher);
        }
        if let Some(ref calls) = m.tool_calls {
            for c in calls {
                c.function.name.hash(&mut hasher);
                c.function.arguments.hash(&mut hasher);
            }
        }
    }
    hasher.finish()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_no_false_positive_under_threshold() {
        let mut guard = LoopGuard::new(3);
        // Two identical calls should not trigger (threshold is 3)
        assert!(
            guard
                .record_tool_call("run_command", "ls", "output")
                .is_none()
        );
        assert!(
            guard
                .record_tool_call("run_command", "ls", "output")
                .is_none()
        );
        // Third identical call should trigger
        assert!(
            guard
                .record_tool_call("run_command", "ls", "output")
                .is_some()
        );
    }

    #[test]
    fn test_different_calls_no_trigger() {
        let mut guard = LoopGuard::new(3);
        assert!(
            guard
                .record_tool_call("run_command", "ls", "output1")
                .is_none()
        );
        assert!(
            guard
                .record_tool_call("run_command", "ls", "output2")
                .is_none()
        );
        assert!(
            guard
                .record_tool_call("run_command", "ls", "output3")
                .is_none()
        );
    }

    #[test]
    fn test_mixed_tools_no_trigger() {
        let mut guard = LoopGuard::new(3);
        assert!(
            guard
                .record_tool_call("run_command", "ls", "output")
                .is_none()
        );
        assert!(
            guard
                .record_tool_call("read_file", "foo", "content")
                .is_none()
        );
        assert!(
            guard
                .record_tool_call("run_command", "ls", "output")
                .is_none()
        );
    }

    #[test]
    fn test_reset_clears_state() {
        let mut guard = LoopGuard::new(3);
        guard.record_tool_call("run_command", "ls", "output");
        guard.record_tool_call("run_command", "ls", "output");
        guard.reset();
        // After reset, should not trigger even with one more identical call
        assert!(
            guard
                .record_tool_call("run_command", "ls", "output")
                .is_none()
        );
    }
}
