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
class ParcelControllerTest {

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
    void trackParcel_shouldReturn200() {
        when(engine.trackParcel(anyString())).thenReturn("Package TRK-00001 is in transit from New York to Los Angeles.");

        String response = restClient().get()
                .uri("/api/parcels/track/TRK-00001")
                .retrieve()
                .body(String.class);

        assertThat(response).contains("TRK-00001");
        assertThat(response).contains("in transit");
    }

    @Test
    void getParcelStatus_shouldReturn200() {
        when(engine.getParcelStatus(anyString())).thenReturn("Package TRK-00001 is currently in transit. Last scanned at New York, NY.");

        String response = restClient().get()
                .uri("/api/parcels/status/TRK-00001")
                .retrieve()
                .body(String.class);

        assertThat(response).contains("TRK-00001");
        assertThat(response).contains("in transit");
    }

    @Test
    void trackParcel_whenEngineFails_shouldReturn500() {
        when(engine.trackParcel(anyString()))
                .thenThrow(new RuntimeException("Tracking failed"));

        ResponseEntity<String> response = restClient().get()
                .uri("/api/parcels/track/TRK-00001")
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
    }

    @Test
    void getParcelStatus_whenEngineFails_shouldReturn500() {
        when(engine.getParcelStatus(anyString()))
                .thenThrow(new RuntimeException("Status check failed"));

        ResponseEntity<String> response = restClient().get()
                .uri("/api/parcels/status/TRK-00001")
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
    }
}