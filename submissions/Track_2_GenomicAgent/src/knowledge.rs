//! Local knowledge retrieval (RAG) over a bundled corpus -- no network,
//! no embedding API, no vector database.
//!
//! Retrieval reuses the exact same Okapi BM25 (+bigram) index and the
//! same GPU compute kernel that `intent.rs` uses for tool planning (see
//! `intent::rank_documents`). That is a deliberate design choice rather
//! than a shortcut: it means the retrieval path inherits a kernel that
//! is already cross-validated against a CPU reference on every run, and
//! it means this crate has one BM25 implementation to verify instead of
//! two. It also makes retrieval genuinely GPU-accelerated on the AMD
//! adapter rather than a separate CPU-only code path.
//!
//! **What this is and isn't:** BM25 retrieval is lexical -- it ranks by
//! real term overlap (with bigram phrase features), not by embedding
//! similarity, so it will not match a paraphrase that shares no
//! vocabulary with the source passage. That is an honest limitation of
//! the method, stated rather than papered over. In exchange it needs no
//! model, no index build step at startup beyond parsing the corpus, and
//! produces a score you can inspect for every passage it returns.

use crate::intent;

/// The bundled corpus, compiled into the binary -- no runtime download,
/// no external file dependency at execution time.
const CORPUS: &str = include_str!("../data/knowledge/methods.md");

/// Minimum BM25 score for a retrieved passage to be considered a real
/// hit rather than incidental word overlap. Chosen against this actual
/// corpus: genuine topical matches score well above this, while a query
/// sharing only a generic word ("the", "data") falls below it. Same
/// judgment-call caveat as `agent::INTENT_THRESHOLD` -- the score for
/// every returned passage is reported so the ranking is auditable.
pub const RETRIEVAL_THRESHOLD: f32 = 1.5;

#[derive(Debug, Clone)]
pub struct Passage {
    pub title: String,
    pub body: String,
}

impl Passage {
    /// Title plus body, which is what actually gets indexed -- the title
    /// carries real topical terms ("Wright's fixation index (FST)") that
    /// should count toward relevance.
    fn indexable(&self) -> String {
        format!("{} {}", self.title, self.body)
    }
}

#[derive(Debug, Clone)]
pub struct Retrieved {
    pub passage: Passage,
    pub score: f32,
}

pub struct KnowledgeBase {
    passages: Vec<Passage>,
    indexable: Vec<String>,
}

impl Default for KnowledgeBase {
    fn default() -> Self {
        Self::new()
    }
}

impl KnowledgeBase {
    pub fn new() -> Self {
        Self::from_markdown(CORPUS)
    }

    /// Split a markdown document into one passage per `##` section.
    /// Content before the first `##` (the corpus preamble) is not a
    /// retrievable passage and is skipped.
    pub fn from_markdown(text: &str) -> Self {
        let mut passages = Vec::new();
        let mut title: Option<String> = None;
        let mut body = String::new();

        for line in text.lines() {
            if let Some(rest) = line.strip_prefix("## ") {
                if let Some(t) = title.take() {
                    passages.push(Passage { title: t, body: body.trim().to_string() });
                }
                title = Some(rest.trim().to_string());
                body.clear();
            } else if title.is_some() {
                body.push_str(line);
                body.push('\n');
            }
        }
        if let Some(t) = title {
            passages.push(Passage { title: t, body: body.trim().to_string() });
        }

        let indexable = passages.iter().map(|p| p.indexable()).collect();
        Self { passages, indexable }
    }

    pub fn len(&self) -> usize {
        self.passages.len()
    }

    /// Retrieve up to `top_k` passages above the relevance threshold,
    /// best first. Returns the compute path actually used so the caller
    /// can report whether retrieval ran on the GPU or fell back to CPU,
    /// exactly like tool planning does.
    pub fn retrieve(&self, query: &str, top_k: usize) -> (Vec<Retrieved>, String) {
        if self.passages.is_empty() {
            return (Vec::new(), "N/A (empty corpus)".to_string());
        }

        let docs: Vec<&str> = self.indexable.iter().map(|s| s.as_str()).collect();
        let (scores, compute_path) = intent::rank_documents(query, &docs);

        let mut ranked: Vec<Retrieved> = self
            .passages
            .iter()
            .zip(scores.iter())
            .map(|(p, &score)| Retrieved { passage: p.clone(), score })
            .collect();
        ranked.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));

        ranked.retain(|r| r.score >= RETRIEVAL_THRESHOLD);
        ranked.truncate(top_k);
        (ranked, compute_path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundled_corpus_parses_into_multiple_passages() {
        let kb = KnowledgeBase::new();
        assert!(
            kb.len() >= 8,
            "expected the bundled corpus to yield several passages, got {}",
            kb.len()
        );
        assert!(kb.passages.iter().all(|p| !p.title.is_empty() && !p.body.is_empty()));
    }

    #[test]
    fn retrieves_the_topically_correct_passage() {
        let kb = KnowledgeBase::new();
        // Each of these should pull back the passage a human would pick.
        let cases = [
            ("what does the fixation index FST measure between subpopulations", "fixation index"),
            ("why would a SNP fail Hardy-Weinberg equilibrium", "Hardy-Weinberg"),
            ("how is a bootstrap confidence interval computed by resampling", "Bootstrap"),
        ];
        for (query, expected_title_fragment) in cases {
            let (hits, _path) = kb.retrieve(query, 3);
            assert!(!hits.is_empty(), "no passage retrieved for {query:?}");
            let top = &hits[0].passage.title;
            assert!(
                top.to_lowercase().contains(&expected_title_fragment.to_lowercase()),
                "for query {query:?} expected a title containing {expected_title_fragment:?}, got {top:?}"
            );
        }
    }

    #[test]
    fn retrieved_text_is_real_corpus_text_not_generated() {
        // Grounding check: whatever comes back must appear verbatim in
        // the bundled corpus. This is the property that separates real
        // retrieval from a model paraphrasing from memory.
        let kb = KnowledgeBase::new();
        let (hits, _) = kb.retrieve("linkage disequilibrium r squared correlation", 2);
        assert!(!hits.is_empty());
        for hit in hits {
            assert!(
                CORPUS.contains(&hit.passage.body),
                "retrieved body is not verbatim corpus text: {:?}",
                hit.passage.title
            );
        }
    }

    #[test]
    fn unrelated_query_returns_nothing_rather_than_a_bad_guess() {
        let kb = KnowledgeBase::new();
        let (hits, _) = kb.retrieve("zzzqqq unrelated aviation turbine maintenance schedule", 3);
        assert!(
            hits.is_empty(),
            "expected no passage above threshold for an unrelated query, got {:?}",
            hits.iter().map(|h| (&h.passage.title, h.score)).collect::<Vec<_>>()
        );
    }

    #[test]
    fn empty_query_never_panics() {
        let kb = KnowledgeBase::new();
        let _ = kb.retrieve("", 3);
        let _ = kb.retrieve("   ", 3);
    }

    #[test]
    fn empty_corpus_is_handled_without_panicking() {
        let kb = KnowledgeBase::from_markdown("# preamble only, no sections\n");
        assert_eq!(kb.len(), 0);
        let (hits, path) = kb.retrieve("anything", 3);
        assert!(hits.is_empty());
        assert!(path.contains("empty corpus"));
    }
}
