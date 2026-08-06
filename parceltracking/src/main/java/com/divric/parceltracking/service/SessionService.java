package com.divric.parceltracking.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Optional;
import java.util.UUID;

/**
 * Data access service for chat session persistence in Neon DB (PostgreSQL).
 * Handles CRUD operations on the chat_sessions table via JdbcTemplate.
 * Logger: info-level logs for all DB operations (persist, fetch, update, delete)
 * with session IDs to trace database activity and debug session lifecycle.
 */
@Service
public class SessionService {

    private static final Logger log = LoggerFactory.getLogger(SessionService.class);

    private final JdbcTemplate jdbcTemplate;

    public SessionService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public void saveSession(UUID sessionId, String metadata) {
        log.info("Persisting new session token to Neon DB — sessionId: {}, metadata: {}", sessionId, metadata);
        jdbcTemplate.update(
            "INSERT INTO chat_sessions (session_id, created_at, last_activity, metadata) VALUES (?, ?, ?, ?)",
            sessionId, LocalDateTime.now(), LocalDateTime.now(), metadata
        );
        log.info("Session token persisted successfully — sessionId: {}", sessionId);
    }

    public Optional<UUID> findSession(UUID sessionId) {
        log.info("Fetching session history from Neon DB — sessionId: {}", sessionId);
        var results = jdbcTemplate.query(
            "SELECT session_id FROM chat_sessions WHERE session_id = ?",
            (rs, rowNum) -> UUID.fromString(rs.getString("session_id")),
            sessionId
        );
        if (results.isEmpty()) {
            log.warn("No session found in DB — sessionId: {}", sessionId);
        } else {
            log.info("Session history retrieved successfully — sessionId: {}", sessionId);
        }
        return results.isEmpty() ? Optional.empty() : Optional.of(results.getFirst());
    }

    public void updateLastActivity(UUID sessionId) {
        log.info("Updating session last activity in Neon DB — sessionId: {}", sessionId);
        jdbcTemplate.update(
            "UPDATE chat_sessions SET last_activity = ? WHERE session_id = ?",
            LocalDateTime.now(), sessionId
        );
        log.info("Session last activity updated successfully — sessionId: {}", sessionId);
    }

    public void deleteSession(UUID sessionId) {
        log.info("Deleting session from Neon DB — sessionId: {}", sessionId);
        jdbcTemplate.update("DELETE FROM chat_sessions WHERE session_id = ?", sessionId);
        log.info("Session deleted successfully from Neon DB — sessionId: {}", sessionId);
    }
}
