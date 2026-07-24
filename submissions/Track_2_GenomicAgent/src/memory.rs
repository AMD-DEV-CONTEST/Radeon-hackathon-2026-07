//! Local multi-turn conversation memory -- bounded, in-process, and
//! never written to disk or sent anywhere.
//!
//! This exists to solve a concrete problem, not to tick a box. The
//! planner (`intent.rs`) is Okapi BM25 over the *current* query's terms.
//! That works well for a self-contained question and fails completely
//! for a natural follow-up: "and its p-value?" or "what about the other
//! one?" carry almost no topical terms of their own, so BM25 has nothing
//! to match and routing degrades to whatever the fallback picks.
//!
//! So memory here does one specific job: when a turn looks like a
//! *referential follow-up* (short, and/or opening with a referring
//! expression), the recent conversation's topical terms are appended to
//! the query before planning, so the follow-up routes to the same
//! subject the user is actually still talking about. A self-contained
//! query is left completely untouched -- augmentation that fired on
//! every turn would drag stale terms into unrelated questions and make
//! routing worse, which is exactly the failure mode this guards against.
//!
//! Everything is bounded (`MAX_TURNS`) so a long session cannot grow
//! memory without limit, and augmentation is capped so an augmented
//! query cannot be swamped by history.

use std::collections::VecDeque;

/// How many turns of history to retain. Small on purpose: conversational
/// reference almost always points at the last turn or two, and a longer
/// window mostly adds stale terms.
pub const MAX_TURNS: usize = 8;

/// How many recent turns contribute terms when augmenting a follow-up.
const CONTEXT_TURNS: usize = 2;

/// A query at or below this many words is treated as likely-referential
/// (e.g. "and the p-value?"). Longer queries are assumed self-contained.
const SHORT_QUERY_WORDS: usize = 6;

/// Opening words that signal the query refers back to something already
/// discussed rather than introducing a new subject.
const REFERRING_OPENERS: &[&str] = &[
    "and", "what about", "how about", "that", "those", "them", "it",
    "its", "their", "the same", "again", "also", "then", "why",
];

#[derive(Debug, Clone)]
pub struct Turn {
    pub query: String,
    pub tools: Vec<String>,
    /// A short digest of what that turn actually produced, kept so the
    /// agent can show the user what it is remembering rather than
    /// claiming an opaque "memory".
    pub digest: String,
}

#[derive(Debug, Default)]
pub struct ConversationMemory {
    turns: VecDeque<Turn>,
}

impl ConversationMemory {
    pub fn new() -> Self {
        Self { turns: VecDeque::new() }
    }

    pub fn len(&self) -> usize {
        self.turns.len()
    }

    /// Most recent turn first.
    pub fn recent(&self, n: usize) -> Vec<&Turn> {
        self.turns.iter().rev().take(n).collect()
    }

    pub fn remember(&mut self, query: &str, tools: &[String], digest: &str) {
        self.turns.push_back(Turn {
            query: query.to_string(),
            tools: tools.to_vec(),
            digest: digest.to_string(),
        });
        while self.turns.len() > MAX_TURNS {
            self.turns.pop_front();
        }
    }

    pub fn clear(&mut self) {
        self.turns.clear();
    }

    /// True if `query` reads like a follow-up that depends on prior
    /// context rather than a self-contained question.
    pub fn looks_referential(query: &str) -> bool {
        let lower = query.trim().to_lowercase();
        if lower.is_empty() {
            return false;
        }
        let word_count = lower.split_whitespace().count();
        let opens_with_reference = REFERRING_OPENERS
            .iter()
            .any(|opener| lower == *opener || lower.starts_with(&format!("{opener} ")));

        opens_with_reference || word_count <= SHORT_QUERY_WORDS
    }

    /// Produce the text that should actually be planned against.
    ///
    /// For a self-contained query this returns the query unchanged and
    /// `false`. For a referential follow-up with history available, it
    /// returns the query plus topical terms drawn from recent turns, and
    /// `true` so the caller can tell the user that context was applied
    /// (this is surfaced in the response, never done silently).
    pub fn augment_query(&self, query: &str) -> (String, bool) {
        if self.turns.is_empty() || !Self::looks_referential(query) {
            return (query.to_string(), false);
        }

        let mut context_terms: Vec<String> = Vec::new();
        for turn in self.recent(CONTEXT_TURNS) {
            for tool in &turn.tools {
                let t = tool.to_lowercase();
                if !context_terms.contains(&t) {
                    context_terms.push(t);
                }
            }
            for word in turn.query.split_whitespace() {
                let w: String = word
                    .chars()
                    .filter(|c| c.is_alphanumeric())
                    .collect::<String>()
                    .to_lowercase();
                if w.len() > 3 && !context_terms.contains(&w) {
                    context_terms.push(w);
                }
            }
        }

        if context_terms.is_empty() {
            return (query.to_string(), false);
        }

        (format!("{} {}", query, context_terms.join(" ")), true)
    }

    /// Human-readable recap, used by the `memory` command in chat mode.
    pub fn summary(&self) -> String {
        if self.turns.is_empty() {
            return "(memory empty -- no turns yet this session)".to_string();
        }
        let mut s = format!("{} turn(s) remembered (most recent last):\n", self.turns.len());
        for (i, turn) in self.turns.iter().enumerate() {
            s.push_str(&format!(
                "  {}. \"{}\" -> [{}] {}\n",
                i + 1,
                turn.query,
                turn.tools.join(", "),
                turn.digest
            ));
        }
        s
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mem_with(queries: &[(&str, &str)]) -> ConversationMemory {
        let mut m = ConversationMemory::new();
        for (q, tool) in queries {
            m.remember(q, &[tool.to_string()], "digest");
        }
        m
    }

    #[test]
    fn memory_is_bounded_and_keeps_the_most_recent_turns() {
        let mut m = ConversationMemory::new();
        for i in 0..(MAX_TURNS + 5) {
            m.remember(&format!("query {i}"), &["Tool".to_string()], "d");
        }
        assert_eq!(m.len(), MAX_TURNS, "memory must not grow without bound");
        let newest = m.recent(1);
        assert_eq!(newest[0].query, format!("query {}", MAX_TURNS + 4));
    }

    #[test]
    fn self_contained_query_is_never_augmented() {
        let m = mem_with(&[("run a population structure PCA", "PopulationStructure")]);
        let long_query = "compute linkage disequilibrium blocks across this chromosome region";
        let (augmented, was_augmented) = m.augment_query(long_query);
        assert!(!was_augmented, "a self-contained query must be left alone");
        assert_eq!(augmented, long_query);
    }

    #[test]
    fn referential_followup_gains_context_from_prior_turns() {
        let m = mem_with(&[("run a selection scan for FST", "SelectionScan")]);
        let (augmented, was_augmented) = m.augment_query("and its p-value?");
        assert!(was_augmented, "a short referential follow-up should be augmented");
        assert!(
            augmented.to_lowercase().contains("selectionscan")
                || augmented.to_lowercase().contains("selection"),
            "augmented query should carry the prior subject: {augmented}"
        );
        assert!(augmented.starts_with("and its p-value?"), "original query text must be preserved");
    }

    #[test]
    fn no_history_means_no_augmentation_even_for_a_followup() {
        let m = ConversationMemory::new();
        let (augmented, was_augmented) = m.augment_query("and that one?");
        assert!(!was_augmented);
        assert_eq!(augmented, "and that one?");
    }

    #[test]
    fn referential_detection_matches_intuition() {
        assert!(ConversationMemory::looks_referential("and the p-value?"));
        assert!(ConversationMemory::looks_referential("what about the other one"));
        assert!(ConversationMemory::looks_referential("why?"));
        assert!(!ConversationMemory::looks_referential(
            "analyze the VCF file and report minor allele frequency and missingness per variant"
        ));
    }

    #[test]
    fn summary_reports_real_remembered_turns() {
        let m = mem_with(&[("first question", "LdBlock"), ("second question", "PcaTool")]);
        let s = m.summary();
        assert!(s.contains("first question") && s.contains("second question"));
        assert!(s.contains("LdBlock") && s.contains("PcaTool"));
    }

    #[test]
    fn empty_memory_summary_is_explicit_not_misleading() {
        let m = ConversationMemory::new();
        assert!(m.summary().contains("empty"));
    }
}
