//! Zero-cost, offline, GPU-dispatched multi-tool intent classification.
//!
//! No external API, no network, no billing, no LLM -- this is the
//! crate's default and only mandatory planning mechanism. It's built
//! from Okapi BM25, a real, classical, decades-old information-
//! retrieval technique -- the ranking function most real search engines
//! actually use -- not a transformer and not a call to any third-party
//! model. It does the one job the crate's original single-keyword
//! router couldn't: select MORE THAN ONE tool for a compound query, by
//! thresholding relevance scores instead of stopping at the first
//! substring match.
//!
//! **Why BM25 and not plain TF-IDF cosine similarity** (which is what
//! this module used before): plain TF-IDF cosine similarity has two
//! real weaknesses for this exact task. First, it doesn't saturate --
//! a term appearing 5 times contributes ~5x the weight of appearing
//! once, even though the 2nd through 5th occurrence tell you almost
//! nothing more than the 1st. BM25's term-frequency saturation
//! (`f*(k1+1) / (f + k1*length_norm)`) flattens that curve, the
//! standard fix. Second, cosine similarity normalizes by vector norm,
//! which under- and over-penalizes documents inconsistently as their
//! length varies; BM25's own length normalization term (`k1`, `b`) is
//! tuned specifically for short-document ranking and is the reason it
//! displaced cosine-TF-IDF in production search systems decades ago.
//! This module also adds bigram features (adjacent-word pairs) on top
//! of unigrams, so an exact multi-word technical phrase shared between
//! a query and a tool's description (e.g. "linkage disequilibrium")
//! scores higher than two documents that merely share the same two
//! words scattered separately.
//!
//! The scoring computation itself is a genuinely new, from-scratch GPU
//! kernel (see shaders/intent_similarity.wgsl, dispatched via
//! gpu_ld::GpuLdContext::compute_bm25_score_batch), cross-validated
//! against a CPU reference the same way every other GPU path in this
//! crate is, with a CPU fallback if no GPU adapter is available.
//!
//! **What this can't do that the optional LLM tier (llm.rs) still can:**
//! write free-form natural-language narration of results. BM25 picks
//! *which* tools apply; it has no language model behind it and cannot
//! generate prose. When no LLM backend is configured, `GenomicAgent`
//! shows raw tool output instead of a narrative -- the same honest
//! fallback as before, just reached via a smarter (and now free,
//! always-available) planning step.

use crate::gpu_ld;
use std::collections::{HashMap, HashSet};

/// Standard Okapi BM25 defaults (Robertson & Sparck Jones), the same
/// values used across most real deployments (e.g. Lucene/Elasticsearch's
/// defaults) -- not tuned or invented for this crate specifically.
const BM25_K1: f32 = 1.2;
const BM25_B: f32 = 0.75;

#[derive(Clone)]
pub struct ToolMatch {
    pub name: String,
    pub score: f32,
}

pub struct IntentResult {
    pub selected: Vec<ToolMatch>,
    pub compute_path: String,
}

fn tokenize_unigrams(text: &str) -> Vec<String> {
    text.to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|s| s.len() > 2)
        .map(|s| s.to_string())
        .collect()
}

/// Unigrams plus adjacent-pair bigrams (e.g. "linkage disequilibrium"
/// tokenizes to "linkage", "disequilibrium", AND
/// "linkage_disequilibrium"). The bigram lets an exact shared phrase
/// score higher than two documents that merely share the same two
/// words in unrelated places.
fn tokenize_with_bigrams(text: &str) -> Vec<String> {
    let unigrams = tokenize_unigrams(text);
    let mut tokens = unigrams.clone();
    for pair in unigrams.windows(2) {
        tokens.push(format!("{}_{}", pair[0], pair[1]));
    }
    tokens
}

/// BM25 index over a fixed, small corpus (here: one document per
/// registered tool's description). IDF is deliberately computed across
/// exactly this corpus, not general English word frequency -- the goal
/// is to weight words/phrases that distinguish between *this crate's*
/// specific tools, not rare words in general.
struct Bm25Index {
    vocab_index: HashMap<String, usize>,
    vocab_len: usize,
    doc_vectors: Vec<Vec<f32>>,
}

impl Bm25Index {
    fn build(documents: &[&str]) -> Self {
        let unigram_tokenized: Vec<Vec<String>> = documents.iter().map(|d| tokenize_unigrams(d)).collect();
        let full_tokenized: Vec<Vec<String>> = documents.iter().map(|d| tokenize_with_bigrams(d)).collect();

        let mut vocab_index: HashMap<String, usize> = HashMap::new();
        for tokens in &full_tokenized {
            for t in tokens {
                let next_idx = vocab_index.len();
                vocab_index.entry(t.clone()).or_insert(next_idx);
            }
        }
        let vocab_len = vocab_index.len();

        let n_docs = documents.len() as f32;
        let mut doc_freq = vec![0u32; vocab_len];
        for tokens in &full_tokenized {
            let mut seen: HashSet<&str> = HashSet::new();
            for t in tokens {
                if seen.insert(t.as_str()) {
                    doc_freq[vocab_index[t]] += 1;
                }
            }
        }
        // Okapi BM25's smoothed IDF: ln((N - df + 0.5) / (df + 0.5) + 1).
        // The "+1" inside the log keeps this non-negative for any df in
        // [0, N] (unlike the classic Robertson/Sparck-Jones form, which
        // can go negative for terms in more than half the corpus) --
        // a standard, widely used variant (e.g. Lucene's default).
        let idf: Vec<f32> = doc_freq
            .iter()
            .map(|&df| ((n_docs - df as f32 + 0.5) / (df as f32 + 0.5) + 1.0).ln())
            .collect();

        // Document length for BM25's length-normalization term is the
        // UNIGRAM count only -- bigrams are a derived, redundant view of
        // the same text, not additional words, and counting them here
        // too would double-penalize longer descriptions.
        let doc_lengths: Vec<f32> = unigram_tokenized.iter().map(|t| t.len() as f32).collect();
        let avgdl = doc_lengths.iter().sum::<f32>() / n_docs.max(1.0);

        let doc_vectors: Vec<Vec<f32>> = full_tokenized
            .iter()
            .zip(doc_lengths.iter())
            .map(|(tokens, &doc_len)| {
                Self::bm25_doc_vector(tokens, &vocab_index, &idf, vocab_len, doc_len, avgdl)
            })
            .collect();

        Self { vocab_index, vocab_len, doc_vectors }
    }

    /// BM25 term weight for every vocab term in one document:
    /// `idf(t) * saturating_tf(t, D)`. Term-frequency saturation (more
    /// occurrences help less and less) and length normalization (a hit
    /// in a short, focused description counts for more than the same
    /// hit in a long, sprawling one) are both applied here, per
    /// document, on the CPU -- the GPU kernel that later scores a query
    /// against these vectors is a plain dot product, deliberately (see
    /// shaders/intent_similarity.wgsl for why).
    fn bm25_doc_vector(
        tokens: &[String],
        vocab_index: &HashMap<String, usize>,
        idf: &[f32],
        vocab_len: usize,
        doc_len: f32,
        avgdl: f32,
    ) -> Vec<f32> {
        let mut tf = vec![0f32; vocab_len];
        for t in tokens {
            if let Some(&idx) = vocab_index.get(t) {
                tf[idx] += 1.0;
            }
        }
        let length_norm = 1.0 - BM25_B + BM25_B * (doc_len / avgdl.max(1.0));
        tf.iter()
            .zip(idf.iter())
            .map(|(&f, &w)| {
                if f <= 0.0 {
                    0.0
                } else {
                    w * (f * (BM25_K1 + 1.0)) / (f + BM25_K1 * length_norm)
                }
            })
            .collect()
    }

    /// Vectorize the query: raw term counts (no saturation -- standard
    /// for short queries, where a term rarely repeats) over the SAME
    /// vocabulary/IDF this index was built from. Words/phrases the
    /// index has never seen are silently ignored -- there's no weight
    /// to assign them, and they can't help match any tool anyway.
    fn vectorize_query(&self, text: &str) -> Vec<f32> {
        let tokens = tokenize_with_bigrams(text);
        let mut v = vec![0f32; self.vocab_len];
        for t in &tokens {
            if let Some(&idx) = self.vocab_index.get(t) {
                v[idx] += 1.0;
            }
        }
        v
    }
}

fn cpu_bm25_batch(query: &[f32], docs: &[Vec<f32>]) -> Vec<f32> {
    docs.iter()
        .map(|d| query.iter().zip(d.iter()).map(|(a, b)| a * b).sum())
        .collect()
}

/// Classify `query` against the registered tools' descriptions using
/// BM25 relevance scoring. Selects every tool scoring at or above
/// `threshold`; if none clear it, falls back to the single best-scoring
/// tool (mirrors the old keyword router's "always route somewhere"
/// behavior -- an agent that finds nothing to do isn't more honest,
/// just less useful).
/// Score `query` against arbitrary `documents` with the same Okapi BM25
/// (+bigram) index and the same GPU kernel `classify` uses, returning the
/// raw per-document scores and which compute path actually ran.
///
/// Exposed because tool planning is not the only thing in this crate that
/// needs "rank these texts against this query": `knowledge.rs` retrieves
/// passages from the local knowledge base with it. Sharing one
/// implementation means the retrieval path inherits the same
/// CPU-cross-validated GPU kernel rather than growing a second, separately
/// -verified copy of BM25.
pub fn rank_documents(query: &str, documents: &[&str]) -> (Vec<f32>, String) {
    let index = Bm25Index::build(documents);
    let query_vec = index.vectorize_query(query);

    let mut doc_flat = Vec::with_capacity(index.doc_vectors.len() * index.vocab_len);
    for v in &index.doc_vectors {
        doc_flat.extend_from_slice(v);
    }

    if index.vocab_len == 0 {
        return (vec![0f32; documents.len()], "N/A (empty vocabulary)".to_string());
    }

    match gpu_ld::GpuLdContext::shared() {
        Ok(ctx) => match ctx.compute_bm25_score_batch(
            &query_vec,
            &doc_flat,
            index.vocab_len,
            documents.len(),
        ) {
            Ok(s) => (s, format!("GPU ({})", ctx.adapter_name)),
            Err(_) => (
                cpu_bm25_batch(&query_vec, &index.doc_vectors),
                "CPU (GPU dispatch failed)".to_string(),
            ),
        },
        Err(_) => (
            cpu_bm25_batch(&query_vec, &index.doc_vectors),
            "CPU (no GPU adapter available)".to_string(),
        ),
    }
}

pub fn classify(
    query: &str,
    tool_names: &[String],
    tool_descriptions: &[String],
    threshold: f32,
) -> IntentResult {
    let documents: Vec<&str> = tool_descriptions.iter().map(|s| s.as_str()).collect();
    let (scores, compute_path) = rank_documents(query, &documents);

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
            2.0,
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
            0.7,
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
        let result = classify("xyzzy plugh quux", &names, &descriptions, 5.0);
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
        let result = classify("", &names, &descriptions, 1.0);
        assert_eq!(result.selected.len(), 1);
    }

    #[test]
    fn shared_exact_phrase_scores_higher_than_scattered_shared_words() {
        // Two tools, both mention "population" and "structure"
        // somewhere, but only one uses them as an adjacent phrase like
        // the query does. BM25 + bigrams should prefer the exact-phrase
        // match.
        let names = vec!["ExactPhrase".to_string(), "ScatteredWords".to_string()];
        let descriptions = vec![
            "Analyze population structure across many samples for research".to_string(),
            "Studies population genetics and the structure of variant calls separately".to_string(),
        ];
        let result = classify("population structure analysis", &names, &descriptions, 0.0);
        assert_eq!(result.selected.first().map(|m| m.name.as_str()), Some("ExactPhrase"));
    }

    #[test]
    fn bm25_score_is_zero_for_completely_disjoint_vocabulary() {
        let (names, descriptions) = sample_tools();
        let index = Bm25Index::build(&descriptions.iter().map(|s| s.as_str()).collect::<Vec<_>>());
        let query_vec = index.vectorize_query("xyzzy plugh quux");
        assert!(query_vec.iter().all(|&x| x == 0.0), "query with no shared vocabulary should vectorize to all zeros");
        let _ = names; // names unused in this test but kept for symmetry with sample_tools()
    }
}
