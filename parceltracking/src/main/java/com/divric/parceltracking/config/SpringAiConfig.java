package com.divric.parceltracking.config;

import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Configuration;

/**
 * Spring AI configuration for local ROCm inference.
 * Auto-configuration from spring-ai-starter-model-openai handles all bean creation
 * based on properties defined in application.yml.
 * Connects to a local OpenAI-compatible endpoint (e.g., Ollama, llama.cpp, vLLM)
 * running on AMD GPU via ROCm. No external API keys required.
 */
@Configuration
public class SpringAiConfig {

    private static final Logger log = LoggerFactory.getLogger(SpringAiConfig.class);

    @PostConstruct
    public void logConfig() {
        String baseUrl = System.getenv().getOrDefault("OPENAI_BASE_URL", "http://localhost:11434/v1");
        String model = System.getenv().getOrDefault("OPENAI_CHAT_MODEL", "llama3.2");
        log.info("Spring AI configured for local ROCm inference — baseUrl={}, model={}", baseUrl, model);
    }
}