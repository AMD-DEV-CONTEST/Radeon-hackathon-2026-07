package com.divric.parceltracking.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * DTO for outgoing chat responses to the frontend.
 * Contains the AI-generated reply and the session ID for context tracking.
 */
@Schema(description = "Response payload returned after processing a chat message")
public class ChatResponse {

    @Schema(description = "The AI-generated reply message", example = "Your package TRK-00001 is currently in transit from New York, NY to Los Angeles, CA. Estimated delivery is August 5, 2026.")
    private String reply;

    @Schema(description = "Session ID for conversation continuity", example = "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    private String sessionId;

    public ChatResponse() {}

    public ChatResponse(String reply, String sessionId) {
        this.reply = reply;
        this.sessionId = sessionId;
    }

    public String getReply() {
        return reply;
    }

    public void setReply(String reply) {
        this.reply = reply;
    }

    public String getSessionId() {
        return sessionId;
    }

    public void setSessionId(String sessionId) {
        this.sessionId = sessionId;
    }
}