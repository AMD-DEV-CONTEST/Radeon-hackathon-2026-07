// Dot product between one BM25 query-term vector and N tool-description
// document vectors, each already BM25-weighted on the CPU side (see
// src/intent.rs). This is the entire "which tool(s) does this query
// need" decision for this crate's default (no-API, no-network, no-cost)
// planning path. Not a transformer, not an external model: a from-
// scratch kernel implementing a classical, well-understood technique
// (Okapi BM25, standard in information retrieval -- what most real
// search engines use), dispatched to real GPU hardware.
//
// This is intentionally a raw dot product, not cosine similarity: BM25
// is not a normalized/angular measure the way cosine similarity is --
// its term-frequency saturation and document-length normalization
// (both applied when the document vector's weights were computed, not
// here) already serve the role vector-norm division would in a cosine
// scheme. Dividing by vector norms on top of that would double up on
// length normalization and distort the ranking BM25 is designed to
// produce.
//
// One GPU thread per document. Workload here (one query vector against
// a handful of tool descriptions, vocab size in the low hundreds once
// bigrams are included) is small enough that per-thread simplicity
// matters more than shaving cycles -- kept simple and auditable over
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
    var score: f32 = 0.0;

    for (var t: u32 = 0u; t < params.vocab_len; t = t + 1u) {
        score = score + query_vec[t] * doc_vectors[base + t];
    }

    out_scores[doc_idx] = score;
}
