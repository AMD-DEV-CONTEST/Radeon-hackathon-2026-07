package com.divric.parceltracking.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * DTO for RAG knowledge base search responses.
 * Contains the original query, the search result, and session ID for context tracking.
 */
@Schema(description = "Response payload returned after searching the RAG knowledge base")
public class RagSearchResponse {

    @Schema(description = "The original search query", example = "What is the refund policy?")
    private String query;

    @Schema(description = "The search result from the knowledge base", example = "Our refund policy allows returns within 30 days of purchase...")
    private String result;

    @Schema(description = "Session ID for context tracking", example = "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    private String sessionId;

    public RagSearchResponse() {}

    public RagSearchResponse(String query, String result, String sessionId) {
        this.query = query;
        this.result = result;
        this.sessionId = sessionId;
    }

    public String getQuery() {
        return query;
    }

    public void setQuery(String query) {
        this.query = query;
    }

    public String getResult() {
        return result;
    }

    public void setResult(String result) {
        this.result = result;
    }

    public String getSessionId() {
        return sessionId;
    }

    public void setSessionId(String sessionId) {
        this.sessionId = sessionId;
    }
}