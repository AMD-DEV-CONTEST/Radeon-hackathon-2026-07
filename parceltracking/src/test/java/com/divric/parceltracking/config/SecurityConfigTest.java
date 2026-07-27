package com.divric.parceltracking.config;

import com.divric.parceltracking.ParceltrackingApplication;
import com.divric.parceltracking.TestConfig;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Import;
import org.springframework.http.*;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(classes = ParceltrackingApplication.class, webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("prod")
@Import(TestConfig.class)
class SecurityConfigTest {

    @LocalServerPort
    private int port;

    @Autowired
    private RestClient.Builder restClientBuilder;

    private RestClient restClient;

    private RestClient restClient() {
        if (restClient == null) {
            restClient = restClientBuilder.baseUrl("http://localhost:" + port).build();
        }
        return restClient;
    }

    @Test
    void adminEndpoint_withoutKey_shouldReturn401() {
        ResponseEntity<String> response = restClient().post()
                .uri("/api/admin/ingest")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"content\":\"test\"}")
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void adminEndpoint_withValidKey_shouldNotReturn401() {
        ResponseEntity<String> response = restClient().post()
                .uri("/api/admin/ingest")
                .header("X-Admin-Key", "test-admin-key")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"content\":\"test\"}")
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        // Should not be 401 - will be 400 (empty content) or 500 (engine mock)
        assertThat(response.getStatusCode()).isNotEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void swaggerEndpoint_shouldBePublic() {
        ResponseEntity<String> response = restClient().get()
                .uri("/swagger-ui.html")
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isNotEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void apiDocsEndpoint_shouldBePublic() {
        ResponseEntity<String> response = restClient().get()
                .uri("/v3/api-docs")
                .retrieve()
                .onStatus(status -> status.isError(), (req, res) -> {})
                .toEntity(String.class);

        assertThat(response.getStatusCode()).isNotEqualTo(HttpStatus.UNAUTHORIZED);
    }
}