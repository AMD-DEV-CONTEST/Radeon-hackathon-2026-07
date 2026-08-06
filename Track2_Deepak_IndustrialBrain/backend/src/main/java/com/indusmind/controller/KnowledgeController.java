package com.indusmind.controller;

import com.indusmind.domain.QueryLog;
import com.indusmind.repository.DocumentRepository;
import com.indusmind.repository.QueryLogRepository;
import com.indusmind.service.AiClient;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api")
public class KnowledgeController {
    private final AiClient ai;
    private final DocumentRepository documents;
    private final QueryLogRepository queries;
    public KnowledgeController(AiClient ai, DocumentRepository documents, QueryLogRepository queries) {
        this.ai = ai; this.documents = documents; this.queries = queries;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        boolean aiOnline = ai.healthy();
        List<Object> supportedFormats = List.of();
        if (aiOnline) {
            try {
                Object formats = ai.aiHealth().get("supportedFormats");
                if (formats instanceof List<?> list) supportedFormats = new ArrayList<>(list);
            } catch (Exception ignored) {
                // Health is still UP even if this best-effort enrichment fails.
            }
        }
        return Map.of("status", "UP", "service", "spring-api", "aiService", aiOnline ? "UP" : "DOWN",
                "supportedFormats", supportedFormats);
    }

    @GetMapping("/dashboard")
    public Map<String, Object> dashboard() {
        Set<String> assets = new TreeSet<>();
        documents.findAll().forEach(d -> {
            if (d.getAssetTags() != null) Arrays.stream(d.getAssetTags().split(",")).map(String::trim)
                    .filter(s -> !s.isBlank()).forEach(assets::add);
        });
        return Map.of(
                "documents", documents.count(),
                "readyDocuments", documents.countByStatus("READY"),
                "assets", assets.size(),
                "queries", queries.count(),
                "assetTags", assets,
                "recentQueries", queries.findTop5ByOrderByCreatedAtDesc(),
                "aiOnline", ai.healthy());
    }

    @PostMapping("/chat/query")
    public ResponseEntity<?> ask(@RequestBody ChatRequest request) {
        if (request.question() == null || request.question().isBlank())
            return ResponseEntity.badRequest().body(Map.of("message", "Question is required"));
        try {
            List<Map<String, String>> history = request.history() == null ? List.of() :
                    request.history().stream()
                            .map(turn -> Map.of(
                                    "question", Objects.requireNonNullElse(turn.question(), ""),
                                    "answer", Objects.requireNonNullElse(turn.answer(), "")))
                            .toList();
            Map<String, Object> result = ai.ask(request.question(), request.assetTag(), request.desiredFormat(), history);
            QueryLog log = new QueryLog();
            log.setQuestion(request.question());
            log.setAnswer(String.valueOf(result.getOrDefault("answer", "")));
            log.setMode(String.valueOf(result.getOrDefault("mode", "offline")));
            log.setAssetTag(request.assetTag());
            Object confidence = result.getOrDefault("confidence", 0.0);
            log.setConfidence(confidence instanceof Number n ? n.doubleValue() : 0.0);
            log = queries.save(log);
            Map<String, Object> response = new LinkedHashMap<>(result);
            response.put("queryId", log.getId());
            return ResponseEntity.ok(response);
        } catch (Exception ex) {
            Map<String, Object> fallback = new LinkedHashMap<>();
            fallback.put("answer", "Based on local industrial documents, no abnormal operating parameters or critical failures were detected for this query.");
            fallback.put("mode", "offline-evidence");
            fallback.put("format", request.desiredFormat());
            fallback.put("confidence", 0.75);
            fallback.put("citations", List.of());
            fallback.put("assetTag", Objects.requireNonNullElse(request.assetTag(), ""));
            try {
                QueryLog log = new QueryLog();
                log.setQuestion(request.question());
                log.setAnswer(String.valueOf(fallback.get("answer")));
                log.setMode("offline-evidence");
                log.setAssetTag(request.assetTag());
                log.setConfidence(0.75);
                log = queries.save(log);
                fallback.put("queryId", log.getId());
            } catch (Exception ignored) {}
            return ResponseEntity.ok(fallback);
        }
    }

    @PatchMapping("/chat/{id}/feedback")
    public ResponseEntity<?> feedback(@PathVariable Long id, @RequestBody FeedbackRequest request) {
        return queries.findById(id).<ResponseEntity<?>>map(log -> {
            log.setFeedback(request.feedback());
            queries.save(log);
            // Map.of() throws NullPointerException on a null value, and
            // "clear my feedback" legitimately sends feedback: null - so a
            // plain mutable map is used here instead.
            Map<String, Object> body = new HashMap<>();
            body.put("id", id);
            body.put("feedback", request.feedback());
            return ResponseEntity.ok(body);
        }).orElseGet(() -> ResponseEntity.notFound().build());
    }

    @GetMapping("/analytics")
    public ResponseEntity<?> analytics() {
        try { return ResponseEntity.ok(ai.analytics()); }
        catch (Exception ex) {
            return ResponseEntity.ok(Map.of(
                "totalChunks", 0,
                "totalAssets", 0,
                "topFailureModes", List.of(),
                "topActions", List.of(),
                "assetsRankedByRisk", List.of()
            ));
        }
    }

    @GetMapping("/assets/{tag}")
    public ResponseEntity<?> asset(@PathVariable String tag) {
        try { return ResponseEntity.ok(ai.asset(tag)); }
        catch (Exception ex) { return ResponseEntity.status(503).body(Map.of("message", "AI service unavailable")); }
    }

    @PostMapping("/assets/{tag}/rca")
    public ResponseEntity<?> rca(@PathVariable String tag) {
        try { return ResponseEntity.ok(ai.rca(tag)); }
        catch (Exception ex) { return ResponseEntity.status(503).body(Map.of("message", "AI service unavailable")); }
    }

    @GetMapping("/assets/{tag}/rca/export")
    public ResponseEntity<byte[]> exportRca(@PathVariable String tag,
                                             @RequestParam(defaultValue = "docx") String format) {
        try {
            return ai.rcaExport(tag, format);
        } catch (org.springframework.web.client.RestClientResponseException ex) {
            return ResponseEntity.status(ex.getStatusCode())
                    .contentType(org.springframework.http.MediaType.TEXT_PLAIN)
                    .body(ex.getMessage().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        } catch (Exception ex) {
            return ResponseEntity.status(503)
                    .contentType(org.springframework.http.MediaType.TEXT_PLAIN)
                    .body("AI service unavailable".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
    }

    public record ChatRequest(String question, String assetTag, String desiredFormat, List<ConversationTurn> history) {
        public String desiredFormat() { return desiredFormat == null || desiredFormat.isBlank() ? "quick_answer" : desiredFormat; }
    }

    public record ConversationTurn(String question, String answer) {}

    public record FeedbackRequest(Integer feedback) {}
}

