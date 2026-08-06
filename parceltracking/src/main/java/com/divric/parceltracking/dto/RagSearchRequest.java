package com.divric.parceltracking.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * DTO for searching the RAG knowledge base directly.
 * Carries the search query and session ID for context.
 */
@Schema(description = "Request payload for searching the RAG knowledge base")
public class RagSearchRequest {

    @Schema(description = "The search query text", example = "What is the refund policy?", requiredMode = Schema.RequiredMode.REQUIRED)
    private String query;

    @Schema(description = "Session ID for context tracking (obtained from POST /api/auth/session)", example = "a1b2c3d4-e5f6-7890-abcd-ef1234567890", requiredMode = Schema.RequiredMode.REQUIRED)
    private String sessionId;

    public RagSearchRequest() {}

    public RagSearchRequest(String query, String sessionId) {
        this.query = query;
        this.sessionId = sessionId;
    }

    public String getQuery() {
        return query;
    }

    public void setQuery(String query) {
        this.query = query;
    }

    public String getSessionId() {
        return sessionId;
    }

    public void setSessionId(String sessionId) {
        this.sessionId = sessionId;
    }
}