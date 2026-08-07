// src/tokenizer.rs
//! Real BPE Tokenizer — loads HuggingFace tokenizer.json and performs proper
//! byte-pair encoding. Handles Qwen special tokens natively.
//!
//! Interface contract:
//!   - encode: &str → Vec<u32>
//!   - decode: &[u32] → String
//!   - load_from_file: parses tokenizer.json (vocab + merges + added_tokens)

use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;
use crate::arena::InferenceArena;
use tracing::info;

#[derive(Debug)]
pub enum TokenizerError {
    IoError(String),
    JsonError(String),
    MalformedVocab,
    BufferOverflow,
}

impl std::fmt::Display for TokenizerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::IoError(e) => write!(f, "IO: {}", e),
            Self::JsonError(e) => write!(f, "JSON: {}", e),
            Self::MalformedVocab => write!(f, "Malformed vocabulary in tokenizer.json"),
            Self::BufferOverflow => write!(f, "Output buffer overflow"),
        }
    }
}

/// Qwen special token IDs (from tokenizer.json added_tokens).
pub struct QwenSpecialTokens {
    pub bos_id: u32,
    pub eos_id: u32,
    pub im_start_id: u32,
    pub im_end_id: u32,
    pub tool_call_id: u32,
    pub tool_exit_id: u32,
}

impl Default for QwenSpecialTokens {
    fn default() -> Self {
        // Qwen2/Qwen2.5 default special token IDs
        Self {
            bos_id: 151643,
            eos_id: 151645,
            im_start_id: 151644,
            im_end_id: 151645,
            tool_call_id: 151646,
            tool_exit_id: 151647,
        }
    }
}

pub struct ZeroAllocBpeTokenizer {
    pub specials: QwenSpecialTokens,
    pub arena: Arc<InferenceArena>,
    /// token string → token ID
    pub vocab: HashMap<String, u32>,
    /// token ID → token string
    pub id_to_token: HashMap<u32, String>,
    /// BPE merge pairs in priority order (index = rank)
    pub merges: Vec<(String, String)>,
    /// Merge pair → rank (for O(1) lookup during encoding)
    pub merge_ranks: HashMap<(String, String), usize>,
    /// Whether a real vocab was loaded (vs fallback byte-level)
    pub has_real_vocab: bool,
}

impl ZeroAllocBpeTokenizer {
    /// Create with fallback byte-level tokenization (no vocab file).
    pub fn new(arena: Arc<InferenceArena>) -> Self {
        Self {
            specials: QwenSpecialTokens::default(),
            arena,
            vocab: HashMap::new(),
            id_to_token: HashMap::new(),
            merges: Vec::new(),
            merge_ranks: HashMap::new(),
            has_real_vocab: false,
        }
    }

    /// Load a real HuggingFace tokenizer.json file.
    /// Schema: { "model": { "vocab": {...}, "merges": [...] }, "added_tokens": [...] }
    pub fn load_from_file(path: &Path, arena: Arc<InferenceArena>) -> Result<Self, TokenizerError> {
        let data = std::fs::read_to_string(path)
            .map_err(|e| TokenizerError::IoError(e.to_string()))?;

        let parsed: serde_json::Value = serde_json::from_str(&data)
            .map_err(|e| TokenizerError::JsonError(e.to_string()))?;

        let mut vocab: HashMap<String, u32> = HashMap::new();
        let mut id_to_token: HashMap<u32, String> = HashMap::new();

        // Parse vocab from model.vocab
        if let Some(vocab_obj) = parsed.get("model").and_then(|m| m.get("vocab")).and_then(|v| v.as_object()) {
            vocab.reserve(vocab_obj.len());
            id_to_token.reserve(vocab_obj.len());
            for (token, id_val) in vocab_obj {
                if let Some(id) = id_val.as_u64() {
                    let id = id as u32;
                    vocab.insert(token.clone(), id);
                    id_to_token.insert(id, token.clone());
                }
            }
        } else {
            return Err(TokenizerError::MalformedVocab);
        }

        // Parse merges from model.merges
        let mut merges: Vec<(String, String)> = Vec::new();
        let mut merge_ranks: HashMap<(String, String), usize> = HashMap::new();

        if let Some(merges_arr) = parsed.get("model").and_then(|m| m.get("merges")).and_then(|v| v.as_array()) {
            merges.reserve(merges_arr.len());
            merge_ranks.reserve(merges_arr.len());
            for (rank, merge_val) in merges_arr.iter().enumerate() {
                if let Some(line) = merge_val.as_str() {
                    let parts: Vec<&str> = line.splitn(2, ' ').collect();
                    if parts.len() == 2 {
                        let pair = (parts[0].to_string(), parts[1].to_string());
                        merge_ranks.insert(pair.clone(), rank);
                        merges.push(pair);
                    }
                }
            }
        }

        // Parse added_tokens for special token IDs
        let mut specials = QwenSpecialTokens::default();
        if let Some(added) = parsed.get("added_tokens").and_then(|v| v.as_array()) {
            for token_obj in added {
                let content = token_obj.get("content").and_then(|v| v.as_str()).unwrap_or("");
                let id = token_obj.get("id").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
                match content {
                    "<|endoftext|>" => specials.eos_id = id,
                    "<|im_start|>" => specials.im_start_id = id,
                    "<|im_end|>" => specials.im_end_id = id,
                    "<tool_call>" => specials.tool_call_id = id,
                    "</tool_call>" => specials.tool_exit_id = id,
                    _ => {}
                }
                // Also add to vocab/id_to_token
                vocab.insert(content.to_string(), id);
                id_to_token.insert(id, content.to_string());
            }
        }

        info!("Tokenizer loaded: {} vocab entries, {} merges", vocab.len(), merges.len());

        Ok(Self {
            specials,
            arena,
            vocab,
            id_to_token,
            merges,
            merge_ranks,
            has_real_vocab: true,
        })
    }

    /// Encode a text string into token IDs using BPE.
    pub fn encode(&self, text: &str) -> Vec<u32> {
        if !self.has_real_vocab {
            // Fallback: byte-level encoding
            return text.bytes().map(|b| b as u32).collect();
        }

        let mut tokens: Vec<u32> = Vec::new();

        // First, split text around special tokens and encode them directly.
        // Special tokens: <|endoftext|>, <|im_start|>, <|im_end|>, <tool_call>, </tool_call>
        let special_patterns: &[(&str, u32)] = &[
            ("<|endoftext|>", self.specials.eos_id),
            ("<|im_start|>", self.specials.im_start_id),
            ("<|im_end|>", self.specials.im_end_id),
            ("<tool_call>", self.specials.tool_call_id),
            ("</tool_call>", self.specials.tool_exit_id),
        ];

        let segments = split_around_special_tokens(text, special_patterns);
        for segment in segments {
            match segment {
                TokenSegment::Special(id) => tokens.push(id),
                TokenSegment::Text(ref s) => {
                    let words = split_into_pretokens(s);
                    for word in &words {
                        if let Some(&id) = self.vocab.get(word.as_str()) {
                            tokens.push(id);
                        } else {
                            let word_tokens = self.bpe_encode_word(word);
                            tokens.extend(word_tokens);
                        }
                    }
                }
            }
        }

        tokens
    }

    /// Apply BPE merges to a single word.
    fn bpe_encode_word(&self, word: &str) -> Vec<u32> {
        // Start with individual characters (or bytes for byte-level BPE)
        let mut pieces: Vec<String> = word.chars().map(|c| c.to_string()).collect();

        if pieces.is_empty() {
            return Vec::new();
        }

        // Iteratively merge the highest-priority pair
        loop {
            if pieces.len() < 2 {
                break;
            }

            // Find the pair with the lowest merge rank (highest priority)
            let mut best_rank = usize::MAX;
            let mut best_idx: Option<usize> = None;

            for i in 0..pieces.len() - 1 {
                let pair = (pieces[i].clone(), pieces[i + 1].clone());
                if let Some(&rank) = self.merge_ranks.get(&pair) {
                    if rank < best_rank {
                        best_rank = rank;
                        best_idx = Some(i);
                    }
                }
            }

            match best_idx {
                Some(idx) => {
                    // Merge the pair
                    let merged = format!("{}{}", pieces[idx], pieces[idx + 1]);
                    pieces[idx] = merged;
                    pieces.remove(idx + 1);
                }
                None => break, // No more merges possible
            }
        }

        // Convert pieces to token IDs
        let mut ids: Vec<u32> = Vec::with_capacity(pieces.len());
        for piece in &pieces {
            if let Some(&id) = self.vocab.get(piece) {
                ids.push(id);
            } else {
                // Unknown piece — encode as individual bytes
                for byte in piece.bytes() {
                    // Qwen uses byte tokens in the vocab as single-byte strings
                    let byte_str = String::from_utf8_lossy(&[byte]).to_string();
                    if let Some(&id) = self.vocab.get(&byte_str) {
                        ids.push(id);
                    } else {
                        // Last resort: use byte value directly (unlikely with full vocab)
                        ids.push(byte as u32);
                    }
                }
            }
        }

        ids
    }

    /// Decode token IDs back to a string.
    pub fn decode(&self, token_ids: &[u32]) -> String {
        if !self.has_real_vocab {
            // Fallback: byte-level decoding
            let bytes: Vec<u8> = token_ids.iter()
                .filter(|&&id| id < 256)
                .map(|&id| id as u8)
                .collect();
            return String::from_utf8_lossy(&bytes).to_string();
        }

        let mut output = String::new();
        for &id in token_ids {
            if let Some(token_str) = self.id_to_token.get(&id) {
                // Qwen uses Ġ (U+0120) to represent a leading space in BPE tokens
                let decoded = token_str.replace('\u{0120}', " ");
                output.push_str(&decoded);
            }
        }
        output
    }

    /// Legacy interface: encode raw bytes into a pre-allocated buffer.
    /// Returns the number of tokens written.
    pub fn encode_text_into_buffer(
        &self,
        raw_text: &[u8],
        output_tokens_slice: &mut [u32],
    ) -> Result<usize, TokenizerError> {
        let text = String::from_utf8_lossy(raw_text);
        let tokens = self.encode(&text);

        if tokens.len() > output_tokens_slice.len() {
            return Err(TokenizerError::BufferOverflow);
        }

        for (i, &id) in tokens.iter().enumerate() {
            output_tokens_slice[i] = id;
        }

        Ok(tokens.len())
    }

    /// Legacy interface: decode token IDs into a pre-allocated byte buffer.
    /// Returns the number of bytes written.
    pub fn decode_tokens_into_bytes(
        &self,
        token_ids: &[u32],
        output_bytes_slice: &mut [u8],
    ) -> Result<usize, TokenizerError> {
        let decoded = self.decode(token_ids);
        let bytes = decoded.as_bytes();

        if bytes.len() > output_bytes_slice.len() {
            return Err(TokenizerError::BufferOverflow);
        }

        output_bytes_slice[..bytes.len()].copy_from_slice(bytes);
        Ok(bytes.len())
    }
}

/// Split text into pre-tokens (words/subwords) for BPE processing.
/// Qwen uses a regex-based pre-tokenizer. This is a simplified version
/// that splits on whitespace and punctuation boundaries.
fn split_into_pretokens(text: &str) -> Vec<String> {
    let mut tokens: Vec<String> = Vec::new();
    let mut current = String::new();

    for ch in text.chars() {
        if ch.is_whitespace() {
            if !current.is_empty() {
                tokens.push(current.clone());
                current.clear();
            }
            // Qwen encodes leading spaces as part of the next token (Ġ prefix)
            current.push('\u{0120}'); // Ġ represents space in BPE vocab
        } else if ch.is_ascii_punctuation() {
            if !current.is_empty() {
                tokens.push(current.clone());
                current.clear();
            }
            tokens.push(ch.to_string());
        } else {
            current.push(ch);
        }
    }

    if !current.is_empty() {
        tokens.push(current);
    }

    tokens
}

/// Segment of text: either a special token (with its ID) or regular text to BPE-encode.
enum TokenSegment {
    Special(u32),
    Text(String),
}

/// Split text around known special token strings, preserving order.
/// Returns segments that are either special tokens (with their IDs) or text chunks.
fn split_around_special_tokens(text: &str, specials: &[(&str, u32)]) -> Vec<TokenSegment> {
    let mut segments: Vec<TokenSegment> = Vec::new();
    let mut remaining = text;

    while !remaining.is_empty() {
        // Find the earliest special token in the remaining text
        let mut earliest_pos = remaining.len();
        let mut earliest_len = 0;
        let mut earliest_id = 0u32;

        for &(pattern, id) in specials {
            if let Some(pos) = remaining.find(pattern) {
                if pos < earliest_pos {
                    earliest_pos = pos;
                    earliest_len = pattern.len();
                    earliest_id = id;
                }
            }
        }

        if earliest_pos == remaining.len() {
            // No more special tokens found — rest is plain text
            segments.push(TokenSegment::Text(remaining.to_string()));
            break;
        }

        // Push text before the special token (if any)
        if earliest_pos > 0 {
            segments.push(TokenSegment::Text(remaining[..earliest_pos].to_string()));
        }

        // Push the special token
        segments.push(TokenSegment::Special(earliest_id));

        // Advance past the special token
        remaining = &remaining[earliest_pos + earliest_len..];
    }

    segments
}
