package com.divric.parceltracking.actor;

import com.divric.parceltracking.actor.protocol.ActorMessage;
import org.apache.pekko.actor.ActorRef;
import org.apache.pekko.actor.ActorSystem;
import org.apache.pekko.pattern.Patterns;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.concurrent.CompletionStage;

import static org.assertj.core.api.Assertions.assertThat;

class IngestionActorTest {

    private ActorSystem actorSystem;
    private ActorRef ingestionActor;

    @BeforeEach
    void setUp() {
        actorSystem = ActorSystem.create("test-system");
        ingestionActor = actorSystem.actorOf(IngestionActor.props(), "ingestion-actor");
    }

    @AfterEach
    void tearDown() {
        actorSystem.terminate();
    }

    @Test
    void ingestDocument_shouldChunkAndReturnResult() throws Exception {
        String content = "First paragraph about parcel tracking.\n\nSecond paragraph about delivery policies.\n\nThird paragraph about refunds.";
        String documentId = "doc-test-001";

        CompletionStage<Object> future = Patterns.ask(
                ingestionActor,
                new ActorMessage.IngestDocument(content, documentId),
                Duration.ofSeconds(5)
        );

        Object response = future.toCompletableFuture().get();
        assertThat(response).isInstanceOf(ActorMessage.WorkerResult.class);

        ActorMessage.WorkerResult result = (ActorMessage.WorkerResult) response;
        assertThat(result.requestId()).isEqualTo(documentId);
        assertThat(result.result().toString()).contains("Ingested document: " + documentId);
        assertThat(result.result().toString()).contains("3 chunks");
    }

    @Test
    void ingestDocument_withEmptyContent_shouldReturnZeroChunks() throws Exception {
        String content = "";
        String documentId = "doc-empty";

        CompletionStage<Object> future = Patterns.ask(
                ingestionActor,
                new ActorMessage.IngestDocument(content, documentId),
                Duration.ofSeconds(5)
        );

        Object response = future.toCompletableFuture().get();
        assertThat(response).isInstanceOf(ActorMessage.WorkerResult.class);

        ActorMessage.WorkerResult result = (ActorMessage.WorkerResult) response;
        assertThat(result.result().toString()).contains("0 chunks");
    }

    @Test
    void ingestDocument_withSingleChunk_shouldReturnOneChunk() throws Exception {
        String content = "Single paragraph without double newlines.";
        String documentId = "doc-single";

        CompletionStage<Object> future = Patterns.ask(
                ingestionActor,
                new ActorMessage.IngestDocument(content, documentId),
                Duration.ofSeconds(5)
        );

        Object response = future.toCompletableFuture().get();
        assertThat(response).isInstanceOf(ActorMessage.WorkerResult.class);

        ActorMessage.WorkerResult result = (ActorMessage.WorkerResult) response;
        assertThat(result.result().toString()).contains("1 chunks");
    }
}