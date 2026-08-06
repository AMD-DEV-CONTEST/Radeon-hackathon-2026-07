package com.divric.parceltracking.actor.protocol;

import java.io.Serializable;

public interface ActorMessage extends Serializable {

    record TrackParcel(String trackingNumber) implements ActorMessage {}
    record GetParcelStatus(String trackingNumber) implements ActorMessage {}
    record IngestDocument(String content, String documentId) implements ActorMessage {}
    record QueryRag(String query, String sessionId) implements ActorMessage {}
    record ChatMessage(String message, String sessionId) implements ActorMessage {}
    record SessionEvent(String sessionId, String event) implements ActorMessage {}
    record EmbeddingQuery(String text) implements ActorMessage {}
    record WorkerResult(String requestId, Object result) implements ActorMessage {}
    record WorkerFailed(String requestId, String error) implements ActorMessage {}
    record Shutdown() implements ActorMessage {}
}