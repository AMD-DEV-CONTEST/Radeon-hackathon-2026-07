package com.divric.parceltracking.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * DTO for admin upload responses sent back to the frontend.
 * Carries status message, uploaded file name, and file size for confirmation.
 */
@Schema(description = "Response payload returned after a document upload or ingest operation")
public class UploadResponse {

    @Schema(description = "Status message indicating success or failure", example = "Document ingested successfully: doc-1712345678000")
    private String message;

    @Schema(description = "Name of the uploaded file", example = "refund_policy.md", nullable = true)
    private String fileName;

    @Schema(description = "Size of the uploaded content in bytes", example = "2450")
    private long fileSize;

    public UploadResponse() {}

    public UploadResponse(String message, String fileName, long fileSize) {
        this.message = message;
        this.fileName = fileName;
        this.fileSize = fileSize;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }

    public String getFileName() {
        return fileName;
    }

    public void setFileName(String fileName) {
        this.fileName = fileName;
    }

    public long getFileSize() {
        return fileSize;
    }

    public void setFileSize(long fileSize) {
        this.fileSize = fileSize;
    }
}