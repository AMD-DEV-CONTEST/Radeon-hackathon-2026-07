package com.divric.parceltracking.service;

import com.divric.parceltracking.actor.protocol.ActorMessage;
import org.apache.pekko.actor.ActorRef;
import org.apache.pekko.pattern.Patterns;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.time.Duration;

/**
 * Service that exposes callable tools for the Spring AI ChatClient.
 * Each @Tool-annotated method is registered as an AI tool the model can invoke:
 * trackParcel, getParcelStatus, searchRag, and ingestDocument.
 * Tools communicate with the Pekko actor system via GatewayActor for async processing.
 * Logger: traces tool invocations and actor responses for debugging AI tool usage.
 */
@Service
public class AgentTools {

    private final ActorRef gatewayActor;

    public AgentTools(ActorRef gatewayActor) {
        this.gatewayActor = gatewayActor;
    }

    @Tool(description = "Track a parcel by its tracking number and get real-time location updates")
    public String trackParcel(String trackingNumber) {
        try {
            return askWorker(new ActorMessage.TrackParcel(trackingNumber));
        } catch (Exception e) {
            return "Error tracking parcel: " + e.getMessage();
        }
    }

    @Tool(description = "Get the current delivery status of a parcel by tracking number")
    public String getParcelStatus(String trackingNumber) {
        try {
            return askWorker(new ActorMessage.GetParcelStatus(trackingNumber));
        } catch (Exception e) {
            return "Error getting status: " + e.getMessage();
        }
    }

    @Tool(description = "Search through ingested documents using RAG (Retrieval Augmented Generation) to find relevant information")
    public String searchRag(String query, String sessionId) {
        try {
            return askWorker(new ActorMessage.QueryRag(query, sessionId));
        } catch (Exception e) {
            return "Error searching RAG: " + e.getMessage();
        }
    }

    @Tool(description = "Ingest a document into the knowledge base for RAG retrieval")
    public String ingestDocument(String content, String documentId) {
        try {
            return askWorker(new ActorMessage.IngestDocument(content, documentId));
        } catch (Exception e) {
            return "Error ingesting document: " + e.getMessage();
        }
    }

    private String askWorker(ActorMessage message) throws Exception {
        return Mono.fromCompletionStage(
                Patterns.ask(gatewayActor, message, Duration.ofSeconds(10))
            )
            .map(response -> {
                if (response instanceof ActorMessage.WorkerResult wr) {
                    return wr.result().toString();
                } else if (response instanceof ActorMessage.WorkerFailed wf) {
                    return "Worker failed: " + wf.error();
                }
                return "Unexpected response: " + response;
            })
            .block();
    }
}