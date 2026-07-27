package com.divric.parceltracking.engine;

import com.divric.parceltracking.actor.protocol.ActorMessage;
import org.apache.pekko.actor.ActorRef;
import org.apache.pekko.pattern.Patterns;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;

/**
 * Engine that bridges REST controllers to the Pekko actor system.
 * Provides both synchronous (blocking) and asynchronous (CompletableFuture) methods
 * that use the ask pattern to communicate with GatewayActor.
 * This decouples HTTP layer from actor messaging details.
 */
@Component
public class SupervisorActorEngine {

    private static final Logger log = LoggerFactory.getLogger(SupervisorActorEngine.class);

    private final ActorRef gatewayActor;
    private final Duration askTimeout = Duration.ofSeconds(10);

    public SupervisorActorEngine(ActorRef gatewayActor) {
        this.gatewayActor = gatewayActor;
        log.info("SupervisorActorEngine connected to GatewayActor at path: /user/gateway");
    }

    // ========== Synchronous (blocking) convenience methods ==========

    /**
     * Track a parcel by tracking number (blocking).
     */
    public String trackParcel(String trackingNumber) {
        log.debug("Engine: Tracking parcel {}", trackingNumber);
        return askWorkerSync(new ActorMessage.TrackParcel(trackingNumber));
    }

    /**
     * Get parcel status by tracking number (blocking).
     */
    public String getParcelStatus(String trackingNumber) {
        log.debug("Engine: Getting status for parcel {}", trackingNumber);
        return askWorkerSync(new ActorMessage.GetParcelStatus(trackingNumber));
    }

    /**
     * Search RAG knowledge base (blocking).
     */
    public String searchRag(String query, String sessionId) {
        log.debug("Engine: Searching RAG for query: {} (session: {})", query, sessionId);
        return askWorkerSync(new ActorMessage.QueryRag(query, sessionId));
    }

    /**
     * Ingest a document into the knowledge base (blocking).
     */
    public String ingestDocument(String content, String documentId) {
        log.debug("Engine: Ingesting document {} ({} chars)", documentId, content.length());
        return askWorkerSync(new ActorMessage.IngestDocument(content, documentId));
    }

    /**
     * Send a chat message to the user session actor (blocking).
     */
    public String sendChatMessage(String message, String sessionId) {
        log.debug("Engine: Sending chat message for session {}", sessionId);
        return askWorkerSync(new ActorMessage.ChatMessage(message, sessionId));
    }

    /**
     * Send a session event to the user session actor (blocking).
     */
    public String sendSessionEvent(String sessionId, String event) {
        log.debug("Engine: Sending session event {} for session {}", event, sessionId);
        return askWorkerSync(new ActorMessage.SessionEvent(sessionId, event));
    }

    // ========== Asynchronous (CompletableFuture) methods ==========

    /**
     * Track a parcel by tracking number (async).
     */
    public CompletableFuture<String> trackParcelAsync(String trackingNumber) {
        log.debug("Engine (async): Tracking parcel {}", trackingNumber);
        return askWorkerAsync(new ActorMessage.TrackParcel(trackingNumber));
    }

    /**
     * Get parcel status by tracking number (async).
     */
    public CompletableFuture<String> getParcelStatusAsync(String trackingNumber) {
        log.debug("Engine (async): Getting status for parcel {}", trackingNumber);
        return askWorkerAsync(new ActorMessage.GetParcelStatus(trackingNumber));
    }

    /**
     * Search RAG knowledge base (async).
     */
    public CompletableFuture<String> searchRagAsync(String query, String sessionId) {
        log.debug("Engine (async): Searching RAG for query: {} (session: {})", query, sessionId);
        return askWorkerAsync(new ActorMessage.QueryRag(query, sessionId));
    }

    /**
     * Ingest a document into the knowledge base (async).
     */
    public CompletableFuture<String> ingestDocumentAsync(String content, String documentId) {
        log.debug("Engine (async): Ingesting document {} ({} chars)", documentId, content.length());
        return askWorkerAsync(new ActorMessage.IngestDocument(content, documentId));
    }

    /**
     * Send a chat message to the user session actor (async).
     */
    public CompletableFuture<String> sendChatMessageAsync(String message, String sessionId) {
        log.debug("Engine (async): Sending chat message for session {}", sessionId);
        return askWorkerAsync(new ActorMessage.ChatMessage(message, sessionId));
    }

    /**
     * Send a session event to the user session actor (async).
     */
    public CompletableFuture<String> sendSessionEventAsync(String sessionId, String event) {
        log.debug("Engine (async): Sending session event {} for session {}", event, sessionId);
        return askWorkerAsync(new ActorMessage.SessionEvent(sessionId, event));
    }

    // ========== Internal methods ==========

    /**
     * Internal blocking method to ask the gateway actor and extract result.
     */
    private String askWorkerSync(ActorMessage message) {
        try {
            CompletionStage<Object> future = Patterns.ask(gatewayActor, message, askTimeout);
            return future.toCompletableFuture()
                    .thenApply(this::extractResult)
                    .exceptionally(e -> "Error: " + e.getMessage())
                    .join();
        } catch (Exception e) {
            log.error("Engine error asking worker: {}", e.getMessage(), e);
            return "Error: " + e.getMessage();
        }
    }

    /**
     * Internal async method to ask the gateway actor and return a CompletableFuture.
     */
    private CompletableFuture<String> askWorkerAsync(ActorMessage message) {
        CompletionStage<Object> future = Patterns.ask(gatewayActor, message, askTimeout);
        return future.toCompletableFuture()
                .thenApply(this::extractResult)
                .exceptionally(e -> {
                    log.error("Engine async error asking worker: {}", e.getMessage(), e);
                    return "Error: " + e.getMessage();
                });
    }

    /**
     * Extract a string result from an actor response.
     */
    private String extractResult(Object response) {
        if (response instanceof ActorMessage.WorkerResult wr) {
            return wr.result().toString();
        } else if (response instanceof ActorMessage.WorkerFailed wf) {
            return "Worker failed: " + wf.error();
        }
        return "Unexpected response: " + response;
    }
}