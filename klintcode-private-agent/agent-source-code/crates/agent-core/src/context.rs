use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::Arc;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio::sync::Mutex;

/// A single block of context (prompt) that can be dynamically loaded or discarded.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillBlock {
    pub id: String,
    pub source: String,
    pub content: String,
    pub is_active: bool,
}

/// Manages a Tree Map of all context blocks, while preserving original insertion order.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextManager {
    pub blocks: BTreeMap<String, SkillBlock>,
    pub order: Vec<String>,
}

impl ContextManager {
    pub fn new() -> Self {
        Self {
            blocks: BTreeMap::new(),
            order: Vec::new(),
        }
    }

    /// Parses a markdown string, extracting `<!-- BLOCK_ID: xxx -->` ... `<!-- /BLOCK_ID: xxx -->`
    pub fn load_from_str(&mut self, source_name: &str, content: &str) {
        let mut global_counter = 0;
        let mut current_block_id = format!("_global_{}_{}", source_name, global_counter);
        let mut current_content = String::new();

        for line in content.lines() {
            if let Some(start_idx) = line.find("<!-- BLOCK_ID: ") {
                if let Some(end_idx) = line[start_idx..].find(" -->") {
                    // Flush the previous block if it has content
                    if !current_content.trim().is_empty() {
                        self.add_block(&current_block_id, source_name, current_content.trim());
                    }

                    let id = line[start_idx + "<!-- BLOCK_ID: ".len()..start_idx + end_idx]
                        .trim()
                        .to_string();
                    current_block_id = id;
                    current_content.clear();
                    continue;
                }
            } else if let Some(start_idx) = line.find("<!-- /BLOCK_ID: ") {
                if let Some(end_idx) = line[start_idx..].find(" -->") {
                    let id = line[start_idx + "<!-- /BLOCK_ID: ".len()..start_idx + end_idx]
                        .trim()
                        .to_string();
                    if id == current_block_id {
                        // Flush the current block
                        self.add_block(&current_block_id, source_name, current_content.trim());
                        global_counter += 1;
                        current_block_id = format!("_global_{}_{}", source_name, global_counter);
                        current_content.clear();
                        continue;
                    }
                }
            }
            current_content.push_str(line);
            current_content.push('\n');
        }

        if !current_content.trim().is_empty() {
            self.add_block(&current_block_id, source_name, current_content.trim());
        }
    }

    fn add_block(&mut self, id: &str, source: &str, content: &str) {
        if !self.blocks.contains_key(id) {
            self.order.push(id.to_string());
        }
        self.blocks.insert(
            id.to_string(),
            SkillBlock {
                id: id.to_string(),
                source: source.to_string(),
                content: content.to_string(),
                is_active: true,
            },
        );
    }

    /// Sets the block to inactive. Returns true if it was actually changed.
    pub fn discard_block(&mut self, id: &str) -> bool {
        if let Some(block) = self.blocks.get_mut(id) {
            if block.is_active {
                block.is_active = false;
                return true;
            }
        }
        false
    }

    /// Renders all active blocks into a single concatenated string.
    pub fn render_active_prompt(&self) -> String {
        let mut result = String::new();
        for id in &self.order {
            if let Some(block) = self.blocks.get(id) {
                if block.is_active {
                    result.push_str(&block.content);
                    result.push_str("\n\n");
                }
            }
        }
        result.trim_end().to_string()
    }
}

/// Spawns a background HTTP server to inspect the context map
pub fn start_debug_server(context: Arc<Mutex<ContextManager>>) {
    tokio::spawn(async move {
        // We bind to 8888. If it fails, another agent loop might already be listening.
        let listener = match TcpListener::bind("127.0.0.1:8888").await {
            Ok(l) => l,
            Err(e) => {
                tracing::debug!(
                    "Could not start debug server on 8888 (probably already running): {}",
                    e
                );
                return;
            }
        };

        tracing::info!("Context debug server listening on http://127.0.0.1:8888/context");

        loop {
            if let Ok((mut stream, _)) = listener.accept().await {
                let context = context.clone();
                tokio::spawn(async move {
                    let mut buffer = [0; 1024];
                    if stream.read(&mut buffer).await.is_ok() {
                        let ctx = context.lock().await;
                        let json = serde_json::to_string_pretty(&ctx.blocks)
                            .unwrap_or_else(|_| "{}".to_string());
                        let response = format!(
                            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
                            json.len(),
                            json
                        );
                        let _ = stream.write_all(response.as_bytes()).await;
                    }
                });
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_context_manager_parsing_and_render() {
        let mut ctx = ContextManager::new();
        let markdown = "This is a global intro.
<!-- BLOCK_ID: phase1 -->
Phase 1 instructions.
<!-- /BLOCK_ID: phase1 -->
Intermediate text.
<!-- BLOCK_ID: phase2 -->
Phase 2 instructions.
<!-- /BLOCK_ID: phase2 -->";

        ctx.load_from_str("SKILL.md", markdown);
        assert_eq!(ctx.blocks.len(), 4); // global before phase1, phase1, global before phase2, phase2

        assert!(ctx.blocks.contains_key("_global_SKILL.md_0"));
        assert!(ctx.blocks.contains_key("_global_SKILL.md_1"));
        assert!(ctx.blocks.contains_key("phase1"));
        assert!(ctx.blocks.contains_key("phase2"));

        let rendered = ctx.render_active_prompt();
        assert!(rendered.contains("This is a global intro."));
        assert!(rendered.contains("Phase 1 instructions."));

        // Assert the order is correct
        assert!(rendered.find("global intro").unwrap() < rendered.find("Phase 1").unwrap());

        let changed = ctx.discard_block("phase1");
        assert!(changed);

        let rendered_after = ctx.render_active_prompt();
        assert!(!rendered_after.contains("Phase 1 instructions."));
        assert!(rendered_after.contains("Phase 2 instructions."));
    }
}
