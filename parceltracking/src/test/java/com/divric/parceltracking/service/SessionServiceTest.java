package com.divric.parceltracking.service;

import com.divric.parceltracking.ParceltrackingApplication;
import com.divric.parceltracking.TestConfig;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(classes = ParceltrackingApplication.class)
@ActiveProfiles("test")
@Import(TestConfig.class)
class SessionServiceTest {

    @Autowired
    private SessionService sessionService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @BeforeEach
    void setUp() {
        jdbcTemplate.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id UUID PRIMARY KEY,
                created_at TIMESTAMP NOT NULL,
                last_activity TIMESTAMP NOT NULL,
                metadata VARCHAR(255)
            )
        """);
    }

    @Test
    void saveSession_shouldPersistSession() {
        UUID sessionId = UUID.randomUUID();

        sessionService.saveSession(sessionId, "test-session");

        Optional<UUID> found = sessionService.findSession(sessionId);
        assertThat(found).isPresent();
        assertThat(found.get()).isEqualTo(sessionId);
    }

    @Test
    void findSession_whenNotExists_shouldReturnEmpty() {
        UUID sessionId = UUID.randomUUID();

        Optional<UUID> found = sessionService.findSession(sessionId);

        assertThat(found).isEmpty();
    }

    @Test
    void deleteSession_shouldRemoveSession() {
        UUID sessionId = UUID.randomUUID();

        sessionService.saveSession(sessionId, "test-session");
        sessionService.deleteSession(sessionId);

        Optional<UUID> found = sessionService.findSession(sessionId);
        assertThat(found).isEmpty();
    }

    @Test
    void updateLastActivity_shouldNotThrow() {
        UUID sessionId = UUID.randomUUID();

        sessionService.saveSession(sessionId, "test-session");
        sessionService.updateLastActivity(sessionId);

        Optional<UUID> found = sessionService.findSession(sessionId);
        assertThat(found).isPresent();
    }
}