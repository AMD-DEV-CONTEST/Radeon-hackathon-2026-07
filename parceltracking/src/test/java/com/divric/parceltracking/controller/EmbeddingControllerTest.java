package com.divric.parceltracking.controller;

import com.divric.parceltracking.ParceltrackingApplication;
import com.divric.parceltracking.TestConfig;
import com.divric.parceltracking.engine.SupervisorActorEngine;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Import;
import org.springframework.http.*;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.web.client.RestClient;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(classes = ParceltrackingApplication.class, webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
@Import(TestConfig.class)
class EmbeddingControllerTest {

    @LocalServerPort
    private int port;

    @Autowired
    private RestClient.Builder restClientBuilder;

    @MockitoBean
    private SupervisorActorEngine engine;

    private RestClient restClient;

    private RestClient restClient() {
        if (restClient == null) {
            restClient = restClientBuilder.baseUrl("http://localhost:" + port).build();
        }
        return restClient;
    }

    @Test
    void generateEmbedding_shouldReturn200() {
        String mockResult = "{\"text\":\"test input\",\"dimensions\":384,\"computeTimeMs\":245,\"gpuAccelerated\":true,\"embeddingPreview\":[0.123,-0.456,0.789,0.012,-0.345,0.678,-0.901,0.234,-0.567,0.890]}";
        when(engine.generateEmbedding(anyString())).thenReturn(mockResult);

        String body = "{\"text\":\"test input\"}";

        String response = restClient().post()
                .uri("/api/embeddings/generate")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(String.class);

        assertThat(response).contains("test input");
        assertThat(response).contains("\"dimensions\":384");
        assertThat(response).contains("\"computeTimeMs\":245");
        assertThat(response).contains("\"gpuAccelerated\":true");
        assertThat(response).contains("0.123");
    }

    @Test
    void generateEmbedding_whenEngineFails_shouldReturn500() {
        when(engine.generateEmbedding(anyString()))
                .thenThrow(new RuntimeException("Embedding generation failed"));

        String body = "{\"text\":\"test input\"}";

        ResponseEntity<String> response = restClient().post()
                .uri("/api/embeddings/generate")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
    }
}