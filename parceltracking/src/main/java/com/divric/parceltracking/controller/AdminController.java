package com.divric.parceltracking.controller;

import com.divric.parceltracking.dto.UploadRequest;
import com.divric.parceltracking.dto.UploadResponse;
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
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

/**
 * REST controller for admin operations — document uploads to the RAG knowledge base.
 * Authenticated via X-Admin-Key header (not session-based) to bypass normal session auth.
 * Supports both multipart file uploads and JSON body uploads (for Swagger UI).
 * Returns proper HTTP status codes: 200 OK, 400 Bad Request, 401 Unauthorized, 500 Server Error.
 */
@RestController
@RequestMapping("/api/admin")
@Tag(name = "Admin", description = "Admin operations — upload and ingest documents into the RAG knowledge base")
public class AdminController {

    private static final Logger log = LoggerFactory.getLogger(AdminController.class);

    private final String adminApiKey;
    private final SupervisorActorEngine engine;

    public AdminController(@Value("${admin.api-key}") String adminApiKey,
                           SupervisorActorEngine engine) {
        this.adminApiKey = adminApiKey;
        this.engine = engine;
    }

    @PostMapping("/upload")
    @Operation(
        summary = "Upload a document file",
        description = "Upload a file (multipart form) to the RAG knowledge base. Requires X-Admin-Key header for authentication."
    )
    @ApiResponses(value = {
        @ApiResponse(
            responseCode = "200",
            description = "File uploaded and ingested successfully",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = UploadResponse.class),
                examples = @ExampleObject(value = "{\"message\":\"File uploaded successfully: doc-1712345678000\",\"fileName\":\"refund_policy.md\",\"fileSize\":2450}"))
        ),
        @ApiResponse(
            responseCode = "400",
            description = "Bad request — no file provided or file is empty",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = UploadResponse.class),
                examples = @ExampleObject(value = "{\"message\":\"No file provided or file is empty\",\"fileName\":null,\"fileSize\":0}"))
        ),
        @ApiResponse(
            responseCode = "401",
            description = "Unauthorized — invalid or missing X-Admin-Key header",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = UploadResponse.class),
                examples = @ExampleObject(value = "{\"message\":\"Invalid or missing X-Admin-Key header\",\"fileName\":null,\"fileSize\":0}"))
        ),
        @ApiResponse(
            responseCode = "500",
            description = "Internal server error — file ingestion failed",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = UploadResponse.class))
        )
    })
    public ResponseEntity<?> uploadDocument(
            @RequestParam("file") MultipartFile file,
            @RequestHeader(value = "X-Admin-Key", required = false) String xAdminKey) {

        ResponseEntity<?> authError = validateAdminKey(xAdminKey);
        if (authError != null) return authError;

        if (file == null || file.isEmpty()) {
            log.warn("Admin upload attempt with no file provided");
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .body(new UploadResponse("No file provided or file is empty", null, 0));
        }

        String fileName = file.getOriginalFilename();
        long fileSize = file.getSize();

        log.info("Admin file upload successful: fileName={}, fileSize={}", fileName, fileSize);

        // Ingest the document content into the RAG pipeline
        try {
            String content = new String(file.getBytes());
            String result = engine.ingestDocument(content, fileName);
            UploadResponse response = new UploadResponse("File uploaded successfully: " + result, fileName, fileSize);
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            log.error("Failed to ingest uploaded file: {}", e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(new UploadResponse("Failed to ingest file: " + e.getMessage(), fileName, fileSize));
        }
    }

    @PostMapping("/ingest")
    @Operation(
        summary = "Ingest document content (JSON)",
        description = "Ingest document content as a JSON payload — suitable for Swagger UI and programmatic API calls. Requires X-Admin-Key header for authentication."
    )
    @ApiResponses(value = {
        @ApiResponse(
            responseCode = "200",
            description = "Document ingested successfully",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = UploadResponse.class),
                examples = @ExampleObject(value = "{\"message\":\"Document ingested successfully: doc-1712345678000\",\"fileName\":\"refund_policy.md\",\"fileSize\":2450}"))
        ),
        @ApiResponse(
            responseCode = "400",
            description = "Bad request — no content provided or content is empty",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = UploadResponse.class),
                examples = @ExampleObject(value = "{\"message\":\"No content provided or content is empty\",\"fileName\":null,\"fileSize\":0}"))
        ),
        @ApiResponse(
            responseCode = "401",
            description = "Unauthorized — invalid or missing X-Admin-Key header",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = UploadResponse.class),
                examples = @ExampleObject(value = "{\"message\":\"Invalid or missing X-Admin-Key header\",\"fileName\":null,\"fileSize\":0}"))
        ),
        @ApiResponse(
            responseCode = "500",
            description = "Internal server error — document ingestion failed",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = UploadResponse.class))
        )
    })
    public ResponseEntity<?> ingestDocument(
            @RequestBody UploadRequest request,
            @RequestHeader(value = "X-Admin-Key", required = false) String xAdminKey) {

        ResponseEntity<?> authError = validateAdminKey(xAdminKey);
        if (authError != null) return authError;

        if (request.getContent() == null || request.getContent().isBlank()) {
            log.warn("Admin ingest attempt with no content");
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .body(new UploadResponse("No content provided or content is empty", null, 0));
        }

        String documentId = request.getDocumentId() != null ? request.getDocumentId() : "doc-" + System.currentTimeMillis();
        log.info("Admin ingest request: documentId={}, fileName={}, contentType={}",
                documentId, request.getFileName(), request.getContentType());

        try {
            String result = engine.ingestDocument(request.getContent(), documentId);
            UploadResponse response = new UploadResponse("Document ingested successfully: " + result,
                    request.getFileName(), request.getContent().length());
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            log.error("Failed to ingest document: {}", e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(new UploadResponse("Failed to ingest document: " + e.getMessage(),
                            request.getFileName(), request.getContent().length()));
        }
    }

    /**
     * Validates the X-Admin-Key header. Returns an error response if invalid, or null if valid.
     */
    private ResponseEntity<?> validateAdminKey(String xAdminKey) {
        if (adminApiKey == null || adminApiKey.isBlank()) {
            log.error("Admin API key is not configured on the server");
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(new UploadResponse("Admin API key not configured on server", null, 0));
        }
        if (xAdminKey == null || !xAdminKey.equals(adminApiKey)) {
            log.warn("Unauthorized admin access attempt with invalid or missing X-Admin-Key header");
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(new UploadResponse("Invalid or missing X-Admin-Key header", null, 0));
        }
        return null;
    }
}