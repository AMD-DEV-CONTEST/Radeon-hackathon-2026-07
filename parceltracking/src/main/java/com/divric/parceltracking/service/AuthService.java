package com.divric.parceltracking.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.UUID;

/**
 * Manages guest session lifecycle — creates new UUID-based sessions and validates
 * existing ones against the Neon DB via SessionService.
 * Logger: info-level logs for new guest UUID generation, warn-level for failed
 * session validation (invalid UUID format or session not found).
 */
@Service
public class AuthService {

    private static final Logger log = LoggerFactory.getLogger(AuthService.class);

    private final SessionService sessionService;

    public AuthService(SessionService sessionService) {
        this.sessionService = sessionService;
    }

    public String createSession() {
        UUID sessionId = UUID.randomUUID();
        log.info("Generating new guest session UUID: {}", sessionId);
        sessionService.saveSession(sessionId, "chat-session");
        return sessionId.toString();
    }

    public boolean validateSession(String sessionIdStr) {
        try {
            if (sessionIdStr == null) {
                log.warn("Session validation failed — null session ID");
                return false;
            }
            UUID sessionId = UUID.fromString(sessionIdStr);
            boolean valid = sessionService.findSession(sessionId).isPresent();
            if (!valid) {
                log.warn("Session validation failed — session not found: {}", sessionIdStr);
            }
            return valid;
        } catch (IllegalArgumentException e) {
            log.warn("Session validation failed — invalid UUID format: {}", sessionIdStr);
            return false;
        }
    }
}
