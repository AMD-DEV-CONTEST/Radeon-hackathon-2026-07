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
@ActiveProfiles("prod")
@Import(TestConfig.class)
class AdminControllerTest {

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
    void ingestDocument_withValidKey_shouldReturn200() {
        when(engine.ingestDocument(anyString(), anyString())).thenReturn("doc-12345");

        String body = "{\"content\":\"Test document content\",\"fileName\":\"test.md\",\"contentType\":\"text/markdown\"}";

        String response = restClient().post()
                .uri("/api/admin/ingest")
                .header("X-Admin-Key", "test-admin-key")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(String.class);

        assertThat(response).contains("Document ingested successfully: doc-12345");
    }

    @Test
    void ingestDocument_withoutKey_shouldReturn401() {
        String body = "{\"content\":\"Test content\"}";

        ResponseEntity<String> response = restClient().post()
                .uri("/api/admin/ingest")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(response.getBody()).contains("Invalid or missing X-Admin-Key header");
    }

    @Test
    void ingestDocument_withWrongKey_shouldReturn401() {
        String body = "{\"content\":\"Test content\"}";

        ResponseEntity<String> response = restClient().post()
                .uri("/api/admin/ingest")
                .header("X-Admin-Key", "wrong-key")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(response.getBody()).contains("Invalid or missing X-Admin-Key header");
    }

    @Test
    void ingestDocument_withEmptyContent_shouldReturn400() {
        String body = "{\"content\":\"\"}";

        ResponseEntity<String> response = restClient().post()
                .uri("/api/admin/ingest")
                .header("X-Admin-Key", "test-admin-key")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).contains("No content provided or content is empty");
    }

    @Test
    void ingestDocument_whenEngineFails_shouldReturn500() {
        when(engine.ingestDocument(anyString(), anyString()))
                .thenThrow(new RuntimeException("Ingestion failed"));

        String body = "{\"content\":\"Test content\",\"fileName\":\"test.md\"}";

        ResponseEntity<String> response = restClient().post()
                .uri("/api/admin/ingest")
                .header("X-Admin-Key", "test-admin-key")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody()).contains("Failed to ingest document: Ingestion failed");
    }
}