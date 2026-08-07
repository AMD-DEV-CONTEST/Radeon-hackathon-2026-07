//! Wayfinder — Semantic Code Search via Qdrant
//! 
//! Wraps Qdrant vector search with embedding generation for code search.
//! Models can call `wayfinder_search("how does paddler routing work")` and
//! get back relevant code snippets from the codebase.

use serde::{Deserialize, Serialize};
use tracing::{info, warn};

/// Embedding service endpoint (embeddinggemma-300m on port 5210)
const EMBEDDING_URL: &str = "http://127.0.0.1:5210/embedding";

/// Qdrant endpoint
const QDRANT_URL: &str = "http://127.0.0.1:6333";

/// Collection name
const COLLECTION_NAME: &str = "codebase_index";

#[derive(Serialize)]
struct EmbeddingRequest {
    content: String,
}

#[derive(Deserialize)]
struct EmbeddingResponse {
    embedding: Vec<f32>,
}

#[derive(Serialize)]
struct QdrantSearchRequest {
    vector: Vec<f32>,
    limit: usize,
    with_payload: bool,
}

#[derive(Deserialize)]
pub struct QdrantSearchResponse {
    pub result: Vec<QdrantPoint>,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct QdrantPoint {
    pub id: serde_json::Value,
    pub score: f32,
    pub payload: Option<serde_json::Value>,
}

/// Search result for models
#[derive(Serialize, Clone)]
pub struct CodeSearchResult {
    pub file_path: String,
    pub function_name: Option<String>,
    pub line_start: Option<u32>,
    pub line_end: Option<u32>,
    pub snippet: String,
    pub score: f32,
}

/// Embed text using the local embedding server
async fn embed_text(text: &str) -> Result<Vec<f32>, String> {
    let client = reqwest::Client::new();
    
    let response = client
        .post(EMBEDDING_URL)
        .json(&EmbeddingRequest {
            content: text.to_string(),
        })
        .send()
        .await
        .map_err(|e| format!("Embedding request failed: {}", e))?;

    if !response.status().is_success() {
        return Err(format!("Embedding server error: {}", response.status()));
    }

    let emb: EmbeddingResponse = response
        .json()
        .await
        .map_err(|e| format!("Failed to parse embedding response: {}", e))?;

    Ok(emb.embedding)
}

/// Search Qdrant with a vector
async fn search_qdrant(vector: Vec<f32>, limit: usize) -> Result<QdrantSearchResponse, String> {
    let client = reqwest::Client::new();
    
    let url = format!("{}/collections/{}/points/search", QDRANT_URL, COLLECTION_NAME);
    
    let request = QdrantSearchRequest {
        vector,
        limit,
        with_payload: true,
    };

    let response = client
        .post(&url)
        .json(&request)
        .send()
        .await
        .map_err(|e| format!("Qdrant search failed: {}", e))?;

    if !response.status().is_success() {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        return Err(format!("Qdrant error {}: {}", status, text));
    }

    let search_resp: QdrantSearchResponse = response
        .json()
        .await
        .map_err(|e| format!("Failed to parse Qdrant response: {}", e))?;

    Ok(search_resp)
}

/// High-level code search: query text → results
pub async fn search_code(query: &str, limit: usize) -> Result<Vec<CodeSearchResult>, String> {
    info!("Wayfinder search: '{}' (limit {})", query, limit);

    // 1. Embed the query
    let vector = embed_text(query).await?;

    // 2. Search Qdrant
    let qdrant_results = search_qdrant(vector, limit).await?;

    // 3. Parse results
    let mut results = Vec::new();

    for point in qdrant_results.result {
        let payload = point.payload.unwrap_or_default();
        
        let file_path = payload
            .get("file_path")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();

        let function_name = payload
            .get("function_name")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let line_start = payload
            .get("line_start")
            .and_then(|v| v.as_u64())
            .map(|n| n as u32);

        let line_end = payload
            .get("line_end")
            .and_then(|v| v.as_u64())
            .map(|n| n as u32);

        let snippet = payload
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        results.push(CodeSearchResult {
            file_path,
            function_name,
            line_start,
            line_end,
            snippet: if snippet.len() > 500 {
                format!("{}...", &snippet[..500])
            } else {
                snippet
            },
            score: point.score,
        });
    }

    info!("Wayfinder found {} results", results.len());
    Ok(results)
}

/// Format results for model consumption
pub fn format_results(results: &[CodeSearchResult]) -> String {
    if results.is_empty() {
        return "No results found.".to_string();
    }

    let mut output = String::from("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
    output.push_str(&format!("WAYFINDER CODE SEARCH RESULTS ({})\n", results.len()));
    output.push_str("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n");

    for (i, res) in results.iter().enumerate() {
        output.push_str(&format!("{}. 📄 {} ", i + 1, res.file_path));
        
        if let Some(func) = &res.function_name {
            output.push_str(&format!("→ `{}`", func));
        }
        
        if let (Some(start), Some(end)) = (res.line_start, res.line_end) {
            output.push_str(&format!(" (lines {}-{})", start, end));
        }
        
        output.push_str(&format!(" [score: {:.3}]\n", res.score));
        output.push_str(&format!("   {}\n\n", res.snippet.replace('\n', "\n   ")));
    }

    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_wayfinder_search() {
        let results = search_code("paddler dispatch routing", 3).await;
        if let Ok(res) = results {
            println!("Found {} results", res.len());
            println!("{}", format_results(&res));
        } else {
            println!("Search failed: {:?}", results);
        }
    }
}
