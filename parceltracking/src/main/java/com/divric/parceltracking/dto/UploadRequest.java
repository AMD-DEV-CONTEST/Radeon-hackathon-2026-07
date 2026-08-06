package com.divric.parceltracking.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * DTO for document upload requests to the admin ingest endpoint.
 * Carries document content, metadata, and content type for RAG pipeline processing.
 */
@Schema(description = "Request payload for ingesting a document into the RAG knowledge base")
public class UploadRequest {

    @Schema(description = "Unique document identifier (auto-generated if not provided)", example = "doc-1712345678000", requiredMode = Schema.RequiredMode.NOT_REQUIRED)
    private String documentId;

    @Schema(description = "The document text content to ingest", example = "Apex Tracking Refund Policy...", requiredMode = Schema.RequiredMode.REQUIRED)
    private String content;

    @Schema(description = "Original file name for reference", example = "refund_policy.md", requiredMode = Schema.RequiredMode.NOT_REQUIRED)
    private String fileName;

    @Schema(description = "MIME content type of the document", example = "text/markdown", requiredMode = Schema.RequiredMode.NOT_REQUIRED)
    private String contentType;

    public UploadRequest() {}

    public UploadRequest(String documentId, String content, String fileName, String contentType) {
        this.documentId = documentId;
        this.content = content;
        this.fileName = fileName;
        this.contentType = contentType;
    }

    public String getDocumentId() {
        return documentId;
    }

    public void setDocumentId(String documentId) {
        this.documentId = documentId;
    }

    public String getContent() {
        return content;
    }

    public void setContent(String content) {
        this.content = content;
    }

    public String getFileName() {
        return fileName;
    }

    public void setFileName(String fileName) {
        this.fileName = fileName;
    }

    public String getContentType() {
        return contentType;
    }

    public void setContentType(String contentType) {
        this.contentType = contentType;
    }
}