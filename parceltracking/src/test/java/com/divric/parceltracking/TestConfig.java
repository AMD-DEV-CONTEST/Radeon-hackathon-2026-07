package com.divric.parceltracking;

import com.divric.parceltracking.service.OnnxSessionManager;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@TestConfiguration
public class TestConfig {

    /**
     * Mock the OnnxSessionManager so tests don't require the 90MB model.onnx file
     * to be present on the classpath. The model is gitignored and downloaded
     * only during Docker container build (prod profile).
     */
    @Bean
    @Primary
    public OnnxSessionManager onnxSessionManager() {
        return mock(OnnxSessionManager.class);
    }

    @Bean
    @Primary
    public ChatModel chatModel() {
        return mock(ChatModel.class);
    }

    @Bean
    @Primary
    public EmbeddingModel embeddingModel() {
        return mock(EmbeddingModel.class);
    }

    @Bean
    @Primary
    public ChatClient.Builder chatClientBuilder() {
        ChatClient.Builder builder = mock(ChatClient.Builder.class);
        ChatClient chatClient = mock(ChatClient.class);
        when(builder.defaultSystem(any(String.class))).thenReturn(builder);
        when(builder.defaultTools(any())).thenReturn(builder);
        when(builder.build()).thenReturn(chatClient);
        return builder;
    }
}