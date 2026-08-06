package com.indusmind.controller;

import com.indusmind.domain.DocumentRecord;
import com.indusmind.repository.DocumentRepository;
import com.indusmind.service.AiClient;
import com.indusmind.service.AuditService;
import com.indusmind.service.DocumentProcessingService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import java.nio.file.*;
import java.security.Principal;
import java.util.*;

@RestController
@RequestMapping("/api/documents")
public class DocumentController {
    private final DocumentRepository documents;
    private final AiClient ai;
    private final DocumentProcessingService processing;
    private final AuditService audit;
    private final Path uploadDir;

    public DocumentController(DocumentRepository documents, AiClient ai, DocumentProcessingService processing,
                               AuditService audit, @Value("${indusmind.upload-dir}") String dir) {
        this.documents = documents; this.ai = ai; this.processing = processing; this.audit = audit;
        this.uploadDir = Path.of(dir).toAbsolutePath().normalize();
    }

    @GetMapping
    public List<DocumentRecord> list() { return documents.findAllByOrderByUploadedAtDesc(); }

    @PostMapping
    public ResponseEntity<?> upload(@RequestParam("file") MultipartFile file, Principal principal) {
        if (file.isEmpty()) return ResponseEntity.badRequest().body(Map.of("message", "Choose a non-empty file"));
        String original = Objects.requireNonNullElse(file.getOriginalFilename(), "document");
        String extension = original.contains(".") ? original.substring(original.lastIndexOf('.')).toLowerCase() : "";
        // Format support (which extensions are readable) is owned entirely by the
        // AI service's extraction registry (ai-service/app/extraction.py) - keeping
        // a second hardcoded list here just lets the two drift out of sync. If the
        // AI service can't read the file, the async job below records a FAILED
        // status with the AI service's own explanation instead of guessing up front.
        DocumentRecord record = new DocumentRecord();
        record.setOriginalName(original);
        record.setStoredName(UUID.randomUUID() + extension);
        record.setContentType(file.getContentType());
        record.setSizeBytes(file.getSize());
        record.setStatus("QUEUED");
        record.setUploadedBy(principal != null ? principal.getName() : "unknown");
        record = documents.save(record);
        try {
            Files.createDirectories(uploadDir);
            Path destination = uploadDir.resolve(record.getStoredName());
            file.transferTo(destination);
            audit.record("DOCUMENT_UPLOADED", "document", String.valueOf(record.getId()), original);
            // Processing (OCR, transcription, embedding) can take anywhere from
            // milliseconds to minutes depending on the file - it happens on a
            // background thread so the upload request returns immediately instead
            // of holding the connection open for a large scan or audio file.
            processing.processAsync(record.getId(), destination, original, record.getUploadedBy());
            return ResponseEntity.status(HttpStatus.ACCEPTED).body(record);
        } catch (Exception ex) {
            record.setStatus("FAILED");
            record.setErrorMessage("Could not save the uploaded file: " + ex.getMessage());
            return ResponseEntity.status(500).body(documents.save(record));
        }
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<?> delete(@PathVariable Long id) {
        DocumentRecord record = documents.findById(id).orElse(null);
        if (record == null) return ResponseEntity.notFound().build();
        try {
            Files.deleteIfExists(uploadDir.resolve(record.getStoredName()));
        } catch (Exception ignored) {
            // Best-effort: an orphaned file on disk is a minor cleanup issue, not
            // a reason to block the user from removing the record and its vectors.
        }
        try {
            ai.deleteDocument(String.valueOf(id));
        } catch (Exception ignored) {
            // The AI service being unreachable shouldn't prevent removing the
            // record itself; re-uploading the same file later is harmless.
        }
        documents.delete(record);
        audit.record("DOCUMENT_DELETED", "document", String.valueOf(id), record.getOriginalName());
        return ResponseEntity.noContent().build();
    }
}
