package com.divric.parceltracking.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * DTO for incoming chat messages from the frontend.
 * Carries the user's message text and their session ID for conversation continuity.
 */
@Schema(description = "Request payload for sending a chat message to the AI assistant")
public class ChatRequest {

    @Schema(description = "The user's message text", example = "Where is my package TRK-00001?", requiredMode = Schema.RequiredMode.REQUIRED)
    private String message;

    @Schema(description = "Session ID for conversation continuity (obtained from POST /api/auth/session)", example = "a1b2c3d4-e5f6-7890-abcd-ef1234567890", requiredMode = Schema.RequiredMode.REQUIRED)
    private String sessionId;

    public ChatRequest() {}

    public ChatRequest(String message, String sessionId) {
        this.message = message;
        this.sessionId = sessionId;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }

    public String getSessionId() {
        return sessionId;
    }

    public void setSessionId(String sessionId) {
        this.sessionId = sessionId;
    }
}