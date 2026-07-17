use serde_json::{json, Value};

pub struct RadeonApi {
    api_key: String,
    client: reqwest::Client,
    base_url: String,
}

impl RadeonApi {
    pub fn new(api_key: String) -> Self {
        Self {
            api_key,
            client: reqwest::Client::new(),
            base_url: "https://developer.amd.com.cn/radeon/api/v1".to_string(),
        }
    }

    pub async fn call_llm(&self, system_prompt: &str, user_query: &str) -> anyhow::Result<String> {
        let start = std::time::Instant::now();

        let payload = json!({
            "model": "Qwen3.6-35B-A3B",
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_query
                }
            ],
            "temperature": 0.7,
            "max_tokens": 500
        });

        let response = self
            .client
            .post(format!("{}/chat/completions", self.base_url))
            .bearer_auth(&self.api_key)
            .json(&payload)
            .send()
            .await;

        let elapsed = start.elapsed().as_secs_f64() * 1000.0;
        tracing::info!("API call latency: {:.2}ms", elapsed);

        match response {
            Ok(resp) => {
                if resp.status().is_success() {
                    let body: Value = resp.json().await?;
                    if let Some(content) = body["choices"][0]["message"]["content"].as_str() {
                        Ok(content.to_string())
                    } else {
                        Err(anyhow::anyhow!("No content in response"))
                    }
                } else {
                    let status = resp.status();
                    tracing::warn!(
                        "API returned non-200: {}. Using fallback.",
                        status
                    );
                    Ok(self.get_fallback_response(user_query))
                }
            }
            Err(e) => {
                tracing::warn!("API call failed: {}. Using fallback.", e);
                Ok(self.get_fallback_response(user_query))
            }
        }
    }

    fn get_fallback_response(&self, query: &str) -> String {
        if query.contains("VCF") || query.contains("SNP") {
            "Based on the genomic data, I recommend using the VcfAnalyzer tool to examine variant distributions and frequencies.".to_string()
        } else if query.contains("linkage") || query.contains("LD") {
            "This query is well-suited for the LdBlock tool to identify linkage disequilibrium patterns.".to_string()
        } else if query.contains("haplotype") {
            "The HaplotypeTool is ideal for analyzing allele patterns and ancestry signals.".to_string()
        } else {
            "I've analyzed your query. The VcfAnalyzer tool can help provide detailed genomic insights.".to_string()
        }
    }
}
