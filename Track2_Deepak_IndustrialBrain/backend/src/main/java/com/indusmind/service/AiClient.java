package com.indusmind.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import java.nio.file.Path;
import java.util.*;

@Service
public class AiClient {
    private final RestClient client;

    public AiClient(@Value("${indusmind.ai-base-url}") String baseUrl,
                     @Value("${indusmind.ai-connect-timeout-ms:5000}") int connectTimeoutMs,
                     @Value("${indusmind.ai-read-timeout-ms:60000}") int readTimeoutMs) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        // Without explicit timeouts this blocks the calling thread indefinitely
        // if the AI service hangs (e.g. a slow local-model load or a stuck OCR job).
        requestFactory.setConnectTimeout(connectTimeoutMs);
        requestFactory.setReadTimeout(readTimeoutMs);
        this.client = RestClient.builder()
                .baseUrl(baseUrl)
                .requestFactory(requestFactory)
                .build();
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> process(Path path, Long documentId, String originalName) {
        return client.post().uri("/ai/documents/process-path")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "file_path", path.toAbsolutePath().normalize().toString(),
                        "document_id", documentId.toString(),
                        "original_name", originalName))
                .retrieve().body(Map.class);
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> ask(String question, String assetTag, String desiredFormat, List<Map<String, String>> history) {
        return client.post().uri("/ai/answer")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "question", question,
                        "asset_tag", assetTag == null ? "" : assetTag,
                        "desired_format", desiredFormat == null || desiredFormat.isBlank() ? "quick_answer" : desiredFormat,
                        "history", history == null ? List.of() : history))
                .retrieve().body(Map.class);
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> analytics() {
        return client.get().uri("/ai/analytics").retrieve().body(Map.class);
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> asset(String tag) {
        return client.get().uri("/ai/assets/{tag}", tag).retrieve().body(Map.class);
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> rca(String tag) {
        return client.post().uri("/ai/rca")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("asset_tag", tag)).retrieve().body(Map.class);
    }

    /** Proxies the AI service's generated docx/pdf/csv straight through, headers included. */
    public ResponseEntity<byte[]> rcaExport(String tag, String format) {
        return client.post().uri("/ai/rca/export")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("asset_tag", tag, "export_format", format))
                .retrieve()
                .toEntity(byte[].class);
    }

    /** Best-effort: removes this document's vectors from the AI service's index. */
    public void deleteDocument(String documentId) {
        client.delete().uri("/ai/documents/{id}", documentId).retrieve().toBodilessEntity();
    }

    public boolean healthy() {
        try { client.get().uri("/ai/health").retrieve().toBodilessEntity(); return true; }
        catch (Exception ex) { return false; }
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> aiHealth() {
        return client.get().uri("/ai/health").retrieve().body(Map.class);
    }
}
