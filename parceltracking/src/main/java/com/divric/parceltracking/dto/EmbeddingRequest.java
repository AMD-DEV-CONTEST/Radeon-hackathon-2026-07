package com.divric.parceltracking.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * DTO for requesting ONNX embedding generation.
 * Accepts text input to be converted into an embedding vector.
 */
@Schema(description = "Request payload for generating an ONNX embedding vector from text")
public class EmbeddingRequest {

    @Schema(description = "The input text to generate an embedding for", example = "What is the refund policy for damaged goods?", requiredMode = Schema.RequiredMode.REQUIRED)
    private String text;

    public EmbeddingRequest() {}

    public EmbeddingRequest(String text) {
        this.text = text;
    }

    public String getText() {
        return text;
    }

    public void setText(String text) {
        this.text = text;
    }
}