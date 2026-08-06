package com.indusmind.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.indusmind.domain.DocumentRecord;
import com.indusmind.repository.DocumentRepository;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientResponseException;
import java.nio.file.Path;
import java.util.Collection;
import java.util.Map;

@Service
public class DocumentProcessingService {
    private final DocumentRepository documents;
    private final AiClient ai;
    private final AuditService audit;

    public DocumentProcessingService(DocumentRepository documents, AiClient ai, AuditService audit) {
        this.documents = documents; this.ai = ai; this.audit = audit;
    }

    // Must live on a different Spring bean than the controller that calls it -
    // @Async only takes effect when invoked through the Spring proxy, and a
    // call from within the same class (self-invocation) would bypass that
    // proxy and simply run synchronously.
    @Async("documentProcessingExecutor")
    public void processAsync(Long documentId, Path destination, String originalName, String actor) {
        DocumentRecord record = documents.findById(documentId).orElse(null);
        if (record == null) return;
        record.setStatus("PROCESSING");
        documents.save(record);
        try {
            Map<String, Object> result = ai.process(destination, documentId, originalName);
            record.setStatus("READY");
            record.setDocumentType(String.valueOf(result.getOrDefault("document_type", "Industrial Document")));
            record.setSummary(String.valueOf(result.getOrDefault("summary", "Document indexed successfully.")));
            Object tags = result.get("asset_tags");
            record.setAssetTags(tags instanceof Collection<?> c ? String.join(", ", c.stream().map(String::valueOf).toList()) : "");
            documents.save(record);
            audit.record(actor, "DOCUMENT_PROCESSED", "document", String.valueOf(documentId), record.getDocumentType());
        } catch (RestClientResponseException ex) {
            // The AI service understood the request but rejected the file itself
            // (unsupported format, spoofed content, unreadable/empty text, ...).
            String message = extractDetail(ex.getResponseBodyAsString());
            record.setStatus("FAILED");
            record.setErrorMessage(message);
            documents.save(record);
            audit.record(actor, "DOCUMENT_FAILED", "document", String.valueOf(documentId), message);
        } catch (Exception ex) {
            record.setStatus("FAILED");
            record.setErrorMessage("AI service unavailable or processing failed: " + ex.getMessage());
            documents.save(record);
            audit.record(actor, "DOCUMENT_FAILED", "document", String.valueOf(documentId), ex.getMessage());
        }
    }

    private String extractDetail(String responseBody) {
        if (responseBody == null || responseBody.isBlank()) return "The AI service rejected this file.";
        try {
            JsonNode node = new ObjectMapper().readTree(responseBody);
            if (node.has("detail")) return node.get("detail").asText();
        } catch (Exception ignored) {
            // Not JSON - fall through and surface the raw body.
        }
        return responseBody;
    }
}
