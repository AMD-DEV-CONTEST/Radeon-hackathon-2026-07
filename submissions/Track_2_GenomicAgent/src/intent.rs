//! Zero-cost, offline, GPU-dispatched multi-tool intent classification.
//!
//! No external API, no network, no billing, no LLM -- this is the
//! crate's default and only mandatory planning mechanism. It's built
//! from a real, classical, well-understood information-retrieval
//! technique (TF-IDF weighted bag-of-words vectors, compared via cosine
//! similarity), not a transformer and not a call to any third-party
//! model. It does the one job the crate's original single-keyword
//! router couldn't: select MORE THAN ONE tool for a compound query, by
//! thresholding similarity scores instead of stopping at the first
//! substring match.
//!
//! The similarity computation itself is a genuinely new, from-scratch
//! GPU kernel (see shaders/intent_similarity.wgsl, dispatched via
//! gpu_ld::GpuLdContext::compute_cosine_similarity_batch), cross-
//! validated against a CPU reference the same way every other GPU path
//! in this crate is, with a CPU fallback if no GPU adapter is available.
//!
//! **What this can't do that the optional LLM tier (llm.rs) still can:**
//! write free-form natural-language narration of results. Vector
//! similarity picks *which* tools apply; it has no language model
//! behind it and cannot generate prose. When no LLM backend is
//! configured, `GenomicAgent` shows raw tool output instead of a
//! narrative -- the same honest fallback as before, just reached via a
//! smarter (and now free, always-available) planning step.

use crate::gpu_ld;
use std::collections::{HashMap, HashSet};

#[derive(Clone)]
pub struct ToolMatch {
    pub name: String,
    pub score: f32,
}

pub struct IntentResult {
    pub selected: Vec<ToolMatch>,
    pub compute_path: String,
}

fn tokenize(text: &str) -> Vec<String> {
    text.to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|s| s.len() > 2)
        .map(|s| s.to_string())
        .collect()
}

/// TF-IDF index over a fixed, small corpus (here: one document per
/// registered tool's description). IDF is deliberately computed across
/// exactly this corpus, not general English word frequency -- the goal
/// is to weight words that distinguish between *this crate's* specific
/// tools, not rare words in general.
struct TfidfIndex {
    vocab_index: HashMap<String, usize>,
    idf: Vec<f32>,
    vocab_len: usize,
    doc_vectors: Vec<Vec<f32>>,
}

impl TfidfIndex {
    fn build(documents: &[&str]) -> Self {
        let tokenized: Vec<Vec<String>> = documents.iter().map(|d| tokenize(d)).collect();

        let mut vocab_index: HashMap<String, usize> = HashMap::new();
        for tokens in &tokenized {
            for t in tokens {
                let next_idx = vocab_index.len();
                vocab_index.entry(t.clone()).or_insert(next_idx);
            }
        }
        let vocab_len = vocab_index.len();

        let n_docs = documents.len() as f32;
        let mut doc_freq = vec![0u32; vocab_len];
        for tokens in &tokenized {
            let mut seen: HashSet<&str> = HashSet::new();
            for t in tokens {
                if seen.insert(t.as_str()) {
                    doc_freq[vocab_index[t]] += 1;
                }
            }
        }
        // Smoothed IDF: ln(n_docs / (1 + df)) + 1, standard smoothing
        // that keeps a word appearing in every document from getting a
        // zero (or negative) weight instead of just a low one.
        let idf: Vec<f32> = doc_freq
            .iter()
            .map(|&df| (n_docs / (1.0 + df as f32)).ln() + 1.0)
            .collect();

        let doc_vectors: Vec<Vec<f32>> = tokenized
            .iter()
            .map(|tokens| Self::tfidf_vector(tokens, &vocab_index, &idf, vocab_len))
            .collect();

        Self { vocab_index, idf, vocab_len, doc_vectors }
    }

    fn tfidf_vector(
        tokens: &[String],
        vocab_index: &HashMap<String, usize>,
        idf: &[f32],
        vocab_len: usize,
    ) -> Vec<f32> {
        let mut tf = vec![0f32; vocab_len];
        let mut counted = 0usize;
        for t in tokens {
            if let Some(&idx) = vocab_index.get(t) {
                tf[idx] += 1.0;
                counted += 1;
            }
        }
        let total = counted.max(1) as f32;
        tf.iter()
            .zip(idf.iter())
            .map(|(&f, &w)| (f / total) * w)
            .collect()
    }

    /// Vectorize a new piece of text (the user's query) against this
    /// index's existing vocabulary/IDF. Words the index has never seen
    /// (not present in any tool description) are silently ignored --
    /// there's no weight to assign them, and they can't help match any
    /// tool anyway.
    fn vectorize(&self, text: &str) -> Vec<f32> {
        let tokens = tokenize(text);
        Self::tfidf_vector(&tokens, &self.vocab_index, &self.idf, self.vocab_len)
    }
}

fn cpu_cosine_batch(query: &[f32], docs: &[Vec<f32>]) -> Vec<f32> {
    docs.iter()
        .map(|d| {
            let dot: f32 = query.iter().zip(d.iter()).map(|(a, b)| a * b).sum();
            let nq = query.iter().map(|x| x * x).sum::<f32>().sqrt();
            let nd = d.iter().map(|x| x * x).sum::<f32>().sqrt();
            if nq <= 0.0 || nd <= 0.0 { 0.0 } else { dot / (nq * nd) }
        })
        .collect()
}

/// Classify `query` against the registered tools' descriptions. Selects
/// every tool scoring at or above `threshold`; if none clear the
/// threshold, falls back to the single best-scoring tool (mirrors the
/// old keyword router's "always route somewhere" behavior -- an agent
/// that finds nothing to do isn't more honest, just less useful).
pub fn classify(
    query: &str,
    tool_names: &[String],
    tool_descriptions: &[String],
    threshold: f32,
) -> IntentResult {
    let documents: Vec<&str> = tool_descriptions.iter().map(|s| s.as_str()).collect();
    let index = TfidfIndex::build(&documents);
    let query_vec = index.vectorize(query);

    let mut doc_flat = Vec::with_capacity(index.doc_vectors.len() * index.vocab_len);
    for v in &index.doc_vectors {
        doc_flat.extend_from_slice(v);
    }

    let (scores, compute_path) = if index.vocab_len == 0 {
        (vec![0f32; documents.len()], "N/A (empty vocabulary)".to_string())
    } else {
        match gpu_ld::GpuLdContext::shared() {
            Ok(ctx) => match ctx.compute_cosine_similarity_batch(
                &query_vec,
                &doc_flat,
                index.vocab_len,
                documents.len(),
            ) {
                Ok(s) => (s, format!("GPU ({})", ctx.adapter_name)),
                Err(_) => (
                    cpu_cosine_batch(&query_vec, &index.doc_vectors),
                    "CPU (GPU dispatch failed)".to_string(),
                ),
            },
            Err(_) => (
                cpu_cosine_batch(&query_vec, &index.doc_vectors),
                "CPU (no GPU adapter available)".to_string(),
            ),
        }
    };

    let mut matches: Vec<ToolMatch> = tool_names
        .iter()
        .zip(scores.iter())
        .map(|(name, &score)| ToolMatch { name: name.clone(), score })
        .collect();
    matches.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));

    let mut selected: Vec<ToolMatch> = matches.iter().filter(|m| m.score >= threshold).cloned().collect();
    if selected.is_empty() {
        if let Some(best) = matches.into_iter().next() {
            selected.push(best);
        }
    }

    IntentResult { selected, compute_path }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_tools() -> (Vec<String>, Vec<String>) {
        let names = vec![
            "VcfAnalyzer".to_string(),
            "LdBlock".to_string(),
            "HaplotypeTool".to_string(),
            "PopulationStructure".to_string(),
        ];
        let descriptions = vec![
            "Parse VCF files and compute SNP statistics count minor allele frequency missingness Hardy-Weinberg equilibrium quality control".to_string(),
            "Identify linkage disequilibrium blocks and tag SNPs via pairwise correlation genetic structure variant independence".to_string(),
            "Tally observed haplotype patterns and frequencies from phased genotypes ancestry inference population genetics".to_string(),
            "GPU-accelerated PCA on sample genetic correlation ancestry population clustering stratification analysis".to_string(),
        ];
        (names, descriptions)
    }

    #[test]
    fn selects_the_single_clearly_relevant_tool_for_an_unambiguous_query() {
        let (names, descriptions) = sample_tools();
        let result = classify(
            "run population structure PCA to check for ancestry clustering",
            &names,
            &descriptions,
            0.2,
        );
        assert_eq!(result.selected.len(), 1, "expected exactly one selected tool, got {:?}", result.selected.iter().map(|m| &m.name).collect::<Vec<_>>());
        assert_eq!(result.selected[0].name, "PopulationStructure");
    }

    #[test]
    fn selects_multiple_tools_for_a_compound_query() {
        let (names, descriptions) = sample_tools();
        // References both haplotype tallying AND SNP/MAF-style QC language.
        let result = classify(
            "find haplotype patterns and frequencies for SNPs with minor allele frequency quality control",
            &names,
            &descriptions,
            0.15,
        );
        let selected_names: Vec<&str> = result.selected.iter().map(|m| m.name.as_str()).collect();
        assert!(selected_names.contains(&"HaplotypeTool"), "expected HaplotypeTool in {selected_names:?}");
        assert!(selected_names.contains(&"VcfAnalyzer"), "expected VcfAnalyzer in {selected_names:?}");
        assert!(result.selected.len() >= 2, "expected a genuine multi-tool selection, got {selected_names:?}");
    }

    #[test]
    fn never_returns_an_empty_selection() {
        let (names, descriptions) = sample_tools();
        // A query sharing essentially no vocabulary with any description.
        let result = classify("xyzzy plugh quux", &names, &descriptions, 0.5);
        assert_eq!(result.selected.len(), 1, "should fall back to single best match, not an empty selection");
    }

    #[test]
    fn identical_text_scores_higher_than_unrelated_text() {
        let (names, descriptions) = sample_tools();
        let result = classify(&descriptions[1].clone(), &names, &descriptions, 0.0);
        // Querying with a tool's own description verbatim should score
        // that exact tool highest of all.
        assert_eq!(result.selected.first().map(|m| m.name.as_str()), Some("LdBlock"));
    }

    #[test]
    fn empty_query_never_panics() {
        let (names, descriptions) = sample_tools();
        let result = classify("", &names, &descriptions, 0.2);
        assert_eq!(result.selected.len(), 1);
    }
}
