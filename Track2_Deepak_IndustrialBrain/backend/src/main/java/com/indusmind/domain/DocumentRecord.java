package com.indusmind.domain;

import jakarta.persistence.*;
import java.time.Instant;

@Entity
@Table(name = "documents")
public class DocumentRecord {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    @Column(nullable = false)
    private String originalName;
    @Column(nullable = false)
    private String storedName;
    private String contentType;
    private long sizeBytes;
    @Column(nullable = false)
    private String status;
    private String documentType;
    private String assetTags;
    @Column(length = 1000)
    private String summary;
    @Column(length = 2000)
    private String errorMessage;
    private String uploadedBy;
    private Instant uploadedAt = Instant.now();

    public Long getId() { return id; }
    public String getOriginalName() { return originalName; }
    public void setOriginalName(String originalName) { this.originalName = originalName; }
    public String getStoredName() { return storedName; }
    public void setStoredName(String storedName) { this.storedName = storedName; }
    public String getContentType() { return contentType; }
    public void setContentType(String contentType) { this.contentType = contentType; }
    public long getSizeBytes() { return sizeBytes; }
    public void setSizeBytes(long sizeBytes) { this.sizeBytes = sizeBytes; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getDocumentType() { return documentType; }
    public void setDocumentType(String documentType) { this.documentType = documentType; }
    public String getAssetTags() { return assetTags; }
    public void setAssetTags(String assetTags) { this.assetTags = assetTags; }
    public String getSummary() { return summary; }
    public void setSummary(String summary) { this.summary = summary; }
    public String getErrorMessage() { return errorMessage; }
    public void setErrorMessage(String errorMessage) { this.errorMessage = errorMessage; }
    public String getUploadedBy() { return uploadedBy; }
    public void setUploadedBy(String uploadedBy) { this.uploadedBy = uploadedBy; }
    public Instant getUploadedAt() { return uploadedAt; }
}
