package com.divric.parceltracking.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * DTO for ONNX embedding generation responses.
 * Contains the original input text, the generated embedding vector (first few dimensions),
 * vector dimension count, and compute timing info for GPU spike observability.
 */
@Schema(description = "Response payload containing the generated ONNX embedding vector and metadata")
public class EmbeddingResponse {

    @Schema(description = "The original input text", example = "What is the refund policy for damaged goods?")
    private String text;

    @Schema(description = "Embedding vector (first 10 dimensions shown for preview)", example = "[0.123, -0.456, 0.789, ...]")
    private double[] embeddingPreview;

    @Schema(description = "Total number of dimensions in the embedding vector", example = "384")
    private int dimensions;

    @Schema(description = "Time taken to generate the embedding in milliseconds", example = "245")
    private long computeTimeMs;

    @Schema(description = "Whether the embedding was computed via GPU (ONNX runtime)", example = "true")
    private boolean gpuAccelerated;

    public EmbeddingResponse() {}

    public EmbeddingResponse(String text, double[] embeddingPreview, int dimensions, long computeTimeMs, boolean gpuAccelerated) {
        this.text = text;
        this.embeddingPreview = embeddingPreview;
        this.dimensions = dimensions;
        this.computeTimeMs = computeTimeMs;
        this.gpuAccelerated = gpuAccelerated;
    }

    public String getText() {
        return text;
    }

    public void setText(String text) {
        this.text = text;
    }

    public double[] getEmbeddingPreview() {
        return embeddingPreview;
    }

    public void setEmbeddingPreview(double[] embeddingPreview) {
        this.embeddingPreview = embeddingPreview;
    }

    public int getDimensions() {
        return dimensions;
    }

    public void setDimensions(int dimensions) {
        this.dimensions = dimensions;
    }

    public long getComputeTimeMs() {
        return computeTimeMs;
    }

    public void setComputeTimeMs(long computeTimeMs) {
        this.computeTimeMs = computeTimeMs;
    }

    public boolean isGpuAccelerated() {
        return gpuAccelerated;
    }

    public void setGpuAccelerated(boolean gpuAccelerated) {
        this.gpuAccelerated = gpuAccelerated;
    }
}