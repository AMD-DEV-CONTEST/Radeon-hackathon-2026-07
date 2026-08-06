package com.divric.parceltracking.controller;

import com.divric.parceltracking.dto.EmbeddingRequest;
import com.divric.parceltracking.dto.EmbeddingResponse;
import com.divric.parceltracking.engine.SupervisorActorEngine;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * REST controller for ONNX embedding model operations.
 * Accepts text input, delegates to EmbeddingWorker via the actor system for
 * GPU-accelerated embedding generation, and returns the vector with metadata.
 * Useful for testing if the ONNX embedding model is working and observing GPU spikes.
 */
@RestController
@RequestMapping("/api/embeddings")
@Tag(name = "Embeddings", description = "ONNX embedding model operations — generate embedding vectors and observe GPU compute")
public class EmbeddingController {

    private static final Logger log = LoggerFactory.getLogger(EmbeddingController.class);

    private final SupervisorActorEngine engine;

    public EmbeddingController(SupervisorActorEngine engine) {
        this.engine = engine;
    }

    @PostMapping("/generate")
    @Operation(
        summary = "Generate an ONNX embedding vector",
        description = "Generate an embedding vector from input text using the ONNX model on GPU. " +
                      "The response includes the embedding preview (first 10 dimensions), dimension count, " +
                      "compute time, and GPU acceleration status. Monitor GPU spikes via ROCm tools (rocm-smi) during this call."
    )
    @ApiResponses(value = {
        @ApiResponse(
            responseCode = "200",
            description = "Embedding generated successfully",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = EmbeddingResponse.class),
                examples = @ExampleObject(value = "{\"text\":\"What is the refund policy for damaged goods?\",\"embeddingPreview\":[0.123,-0.456,0.789,0.012,-0.345,0.678,-0.901,0.234,-0.567,0.890],\"dimensions\":384,\"computeTimeMs\":245,\"gpuAccelerated\":true}"))
        ),
        @ApiResponse(
            responseCode = "400",
            description = "Invalid request — missing or empty text",
            content = @Content
        ),
        @ApiResponse(
            responseCode = "500",
            description = "Internal server error — embedding generation failed",
            content = @Content
        )
    })
    public ResponseEntity<?> generateEmbedding(@RequestBody EmbeddingRequest request) {
        try {
            log.info("EmbeddingController: Generating embedding for text ({} chars)", request.getText().length());

            String result = engine.generateEmbedding(request.getText());

            // Parse the JSON result from the EmbeddingWorker
            // The worker returns a JSON string with text, dimensions, computeTimeMs, gpuAccelerated, embeddingPreview
            EmbeddingResponse response = parseEmbeddingResult(request.getText(), result);
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            log.error("Embedding generation failed: {}", e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(new EmbeddingResponse(request.getText(), new double[0], 0, 0, false));
        }
    }

    /**
     * Parses the JSON result string from EmbeddingWorker into an EmbeddingResponse DTO.
     */
    private EmbeddingResponse parseEmbeddingResult(String originalText, String jsonResult) {
        // Extract fields from the JSON result using simple string parsing
        // Format: {"text":"...","dimensions":384,"computeTimeMs":245,"gpuAccelerated":true,"embeddingPreview":[0.123,...]}
        try {
            int dimStart = jsonResult.indexOf("\"dimensions\":") + "\"dimensions\":".length();
            int dimEnd = jsonResult.indexOf(",", dimStart);
            int dimensions = Integer.parseInt(jsonResult.substring(dimStart, dimEnd).trim());

            int timeStart = jsonResult.indexOf("\"computeTimeMs\":") + "\"computeTimeMs\":".length();
            int timeEnd = jsonResult.indexOf(",", timeStart);
            long computeTimeMs = Long.parseLong(jsonResult.substring(timeStart, timeEnd).trim());

            boolean gpuAccelerated = jsonResult.contains("\"gpuAccelerated\":true");

            int previewStart = jsonResult.indexOf("\"embeddingPreview\":[") + "\"embeddingPreview\":[".length();
            int previewEnd = jsonResult.indexOf("]", previewStart);
            String previewStr = jsonResult.substring(previewStart, previewEnd);

            String[] parts = previewStr.split(",");
            double[] preview = new double[parts.length];
            for (int i = 0; i < parts.length; i++) {
                preview[i] = Double.parseDouble(parts[i].trim());
            }

            return new EmbeddingResponse(originalText, preview, dimensions, computeTimeMs, gpuAccelerated);
        } catch (Exception e) {
            log.error("Failed to parse embedding result: {}", e.getMessage(), e);
            return new EmbeddingResponse(originalText, new double[0], 0, 0, false);
        }
    }
}