package com.divric.parceltracking.config;

import com.divric.parceltracking.service.OnnxSessionManager;
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
 * <p>
 * The ONNX embedding session is managed by {@link OnnxSessionManager}, which is
 * initialized at startup with ROCm/MIGraphX priority and CPU fallback.
 * </p>
 */
@Configuration
public class SpringAiConfig {

    private static final Logger log = LoggerFactory.getLogger(SpringAiConfig.class);

    private final OnnxSessionManager onnxSessionManager;

    public SpringAiConfig(OnnxSessionManager onnxSessionManager) {
        this.onnxSessionManager = onnxSessionManager;
    }

    @PostConstruct
    public void logConfig() {
        String baseUrl = System.getenv().getOrDefault("OPENAI_BASE_URL", "http://localhost:11434/v1");
        String model = System.getenv().getOrDefault("OPENAI_CHAT_MODEL", "llama3.2");
        log.info("Spring AI configured for local ROCm inference — baseUrl={}, model={}", baseUrl, model);

        // Log ONNX Runtime execution provider status
        String provider = onnxSessionManager.getActiveProvider();
        boolean gpu = onnxSessionManager.isGpuAvailable();
        log.info("ONNX Runtime execution provider: {} (GPU accelerated: {})", provider, gpu);

        if (gpu) {
            log.info("AMD GPU detected — ONNX embeddings will run on ROCm/MIGraphX");
        } else {
            log.info("No AMD GPU detected — ONNX embeddings falling back to CPU with {} threads",
                    Runtime.getRuntime().availableProcessors());
        }
    }
}
