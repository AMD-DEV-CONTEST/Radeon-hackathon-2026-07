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
class ChatControllerTest {

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
    void chat_shouldReturn200() {
        when(engine.sendChatMessage(anyString(), anyString())).thenReturn("Your package TRK-00001 is in transit.");

        String body = "{\"message\":\"Where is my package?\",\"sessionId\":\"test-session-id\"}";

        String response = restClient().post()
                .uri("/api/chat")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(String.class);

        assertThat(response).contains("Your package TRK-00001 is in transit.");
        assertThat(response).contains("test-session-id");
    }

    @Test
    void searchRag_shouldReturn200() {
        when(engine.searchRag(anyString(), anyString())).thenReturn("RAG result for query: \"What is the refund policy?\"");

        String body = "{\"query\":\"What is the refund policy?\",\"sessionId\":\"test-session-id\"}";

        String response = restClient().post()
                .uri("/api/chat/rag")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(String.class);

        assertThat(response).contains("RAG result for query");
        assertThat(response).contains("What is the refund policy?");
        assertThat(response).contains("test-session-id");
    }

    @Test
    void searchRag_whenEngineFails_shouldReturn500() {
        when(engine.searchRag(anyString(), anyString()))
                .thenThrow(new RuntimeException("Search failed"));

        String body = "{\"query\":\"test query\",\"sessionId\":\"test-session-id\"}";

        ResponseEntity<String> response = restClient().post()
                .uri("/api/chat/rag")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
    }
}