package com.divric.parceltracking.actor;

import com.divric.parceltracking.actor.protocol.ActorMessage;
import org.apache.pekko.actor.AbstractActor;
import org.apache.pekko.actor.Props;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Pekko actor that runs the RAG document ingestion pipeline.
 * Receives IngestDocument messages, chunks the text, generates embeddings,
 * and pushes vectors to pgvector. Each step is logged for pipeline observability.
 * Logger: info-level logs for each RAG stage (payload received, chunk count,
 * embedding generation, pgvector push) to trace the full ingestion flow.
 */
public class IngestionActor extends AbstractActor {

    private static final Logger log = LoggerFactory.getLogger(IngestionActor.class);

    public static Props props() {
        return Props.create(IngestionActor.class, IngestionActor::new);
    }

    @Override
    public Receive createReceive() {
        return receiveBuilder()
            .match(ActorMessage.IngestDocument.class, this::onIngestDocument)
            .build();
    }

    private void onIngestDocument(ActorMessage.IngestDocument msg) {
        log.info("RAG pipeline: Payload received — documentId: {}, contentLength: {} chars",
                msg.documentId(), msg.content().length());

        // Step 1: Chunk the document text
        String[] chunks = chunkText(msg.content());
        log.info("RAG pipeline: Text chunking complete — documentId: {}, chunkCount: {}",
                msg.documentId(), chunks.length);

        // Step 2: Generate embeddings for each chunk
        log.info("RAG pipeline: Generating embeddings — documentId: {}, chunkCount: {}",
                msg.documentId(), chunks.length);
        double[][] embeddings = generateEmbeddings(chunks);
        log.info("RAG pipeline: Embedding generation complete — documentId: {}, embeddingDim: {}",
                msg.documentId(), embeddings.length > 0 ? embeddings[0].length : 0);

        // Step 3: Push to pgvector
        log.info("RAG pipeline: Pushing to pgvector — documentId: {}, vectorCount: {}",
                msg.documentId(), embeddings.length);
        pushToPgvector(msg.documentId(), chunks, embeddings);
        log.info("RAG pipeline: pgvector push complete — documentId: {}", msg.documentId());

        String result = "Ingested document: " + msg.documentId() + " (" + msg.content().length() + " chars, "
                + chunks.length + " chunks)";
        getSender().tell(new ActorMessage.WorkerResult(msg.documentId(), result), getSelf());
    }

    private String[] chunkText(String content) {
        // Simple chunking: split by double newlines for now
        // In production this would use a proper text splitter
        if (content == null || content.isBlank()) {
            return new String[0];
        }
        return content.split("\\n\\n+");
    }

    private double[][] generateEmbeddings(String[] chunks) {
        // Placeholder — in production this would call an embedding API
        double[][] embeddings = new double[chunks.length][384];
        for (int i = 0; i < chunks.length; i++) {
            // Simulated embedding vector
            for (int j = 0; j < 384; j++) {
                embeddings[i][j] = Math.random();
            }
        }
        return embeddings;
    }

    private void pushToPgvector(String documentId, String[] chunks, double[][] embeddings) {
        // Placeholder — in production this would batch insert into pgvector
        log.debug("pgvector insert placeholder — documentId: {}, chunks: {}, vectors: {}",
                documentId, chunks.length, embeddings.length);
    }
}
