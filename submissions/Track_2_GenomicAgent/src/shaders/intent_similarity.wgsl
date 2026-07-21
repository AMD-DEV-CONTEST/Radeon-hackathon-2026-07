// Cosine similarity between one TF-IDF query vector and N tool-description
// document vectors. This is the entire "which tool(s) does this query
// need" decision for this crate's default (no-API, no-network, no-cost)
// planning path -- see src/intent.rs for the vectorization that builds
// these vectors and src/agent.rs for how the scores are thresholded into
// a tool selection. Not a transformer, not an external model: a from-
// scratch kernel implementing a classical, well-understood technique
// (bag-of-words / TF-IDF + cosine similarity, standard in information
// retrieval), dispatched to real GPU hardware.
//
// One GPU thread per document. Recomputes the query's own norm once per
// thread rather than once total -- wasteful in the abstract, but the
// actual workload here (one query vector against a handful of tool
// descriptions, vocab size in the tens of words) is small enough that
// this doesn't matter in practice; kept simple and auditable over
// maximally efficient, same tradeoff philosophy as the rest of this
// crate's GPU code.

struct Params {
    vocab_len: u32,
    num_docs: u32,
    _pad0: u32,
    _pad1: u32,
};

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var<storage, read> query_vec: array<f32>;      // [vocab_len]
@group(0) @binding(2) var<storage, read> doc_vectors: array<f32>;    // [doc_idx * vocab_len + term_idx]
@group(0) @binding(3) var<storage, read_write> out_scores: array<f32>; // [doc_idx]

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let doc_idx = gid.x;
    if (doc_idx >= params.num_docs) {
        return;
    }

    let base = doc_idx * params.vocab_len;
    var dot: f32 = 0.0;
    var norm_q: f32 = 0.0;
    var norm_d: f32 = 0.0;

    for (var t: u32 = 0u; t < params.vocab_len; t = t + 1u) {
        let q = query_vec[t];
        let d = doc_vectors[base + t];
        dot = dot + q * d;
        norm_q = norm_q + q * q;
        norm_d = norm_d + d * d;
    }

    let denom = sqrt(norm_q) * sqrt(norm_d);
    if (denom <= 0.0) {
        out_scores[doc_idx] = 0.0;
    } else {
        out_scores[doc_idx] = dot / denom;
    }
}
