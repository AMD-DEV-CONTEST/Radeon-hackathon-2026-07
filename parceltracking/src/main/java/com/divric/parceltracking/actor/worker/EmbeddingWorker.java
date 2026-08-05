package com.divric.parceltracking.actor.worker;

import com.divric.parceltracking.actor.protocol.ActorMessage;
import com.divric.parceltracking.service.OnnxSessionManager;
import org.apache.pekko.actor.AbstractActor;
import org.apache.pekko.actor.Props;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtSession;

/**
 * Pekko actor that generates embeddings using the ONNX model (all-MiniLM-L6-v2)
 * via the shared {@link OnnxSessionManager}. The ONNX session is initialized once
 * at application startup by OnnxSessionManager, which handles ROCm/MIGraphX GPU
 * acceleration or CPU fallback automatically.
 * <p>
 * This actor delegates all ONNX Runtime operations to the session manager,
 * avoiding redundant model loading and execution provider negotiation per request.
 * </p>
 */
public class EmbeddingWorker extends AbstractActor {

    private static final Logger log = LoggerFactory.getLogger(EmbeddingWorker.class);

    private final OnnxSessionManager sessionManager;

    public EmbeddingWorker(OnnxSessionManager sessionManager) {
        this.sessionManager = sessionManager;
    }

    public static Props props(OnnxSessionManager sessionManager) {
        return Props.create(EmbeddingWorker.class, () -> new EmbeddingWorker(sessionManager));
    }

    @Override
    public Receive createReceive() {
        return receiveBuilder()
            .match(ActorMessage.EmbeddingQuery.class, this::onEmbeddingQuery)
            .build();
    }

    private void onEmbeddingQuery(ActorMessage.EmbeddingQuery msg) {
        log.info("EmbeddingWorker: Generating embedding for text: \"{}\" ({} chars)",
                msg.text().length() > 50 ? msg.text().substring(0, 50) + "..." : msg.text(),
                msg.text().length());

        long startTime = System.currentTimeMillis();

        try {
            double[] embedding = generateEmbedding(msg.text());
            long computeTimeMs = System.currentTimeMillis() - startTime;

            log.info("EmbeddingWorker: Embedding generated — dim: {}, computeTimeMs: {}, provider: {}",
                    OnnxSessionManager.EMBEDDING_DIM, computeTimeMs, sessionManager.getActiveProvider());

            String result = String.format(
                "{\"text\":\"%s\",\"dimensions\":%d,\"computeTimeMs\":%d,\"gpuAccelerated\":%b,\"embeddingPreview\":[%s]}",
                escapeJson(msg.text()),
                OnnxSessionManager.EMBEDDING_DIM,
                computeTimeMs,
                sessionManager.isGpuAvailable(),
                formatPreview(embedding)
            );

            getSender().tell(new ActorMessage.WorkerResult(msg.text(), result), getSelf());
        } catch (Exception e) {
            log.error("EmbeddingWorker: Failed to generate embedding: {}", e.getMessage(), e);
            String errorResult = String.format(
                "{\"text\":\"%s\",\"dimensions\":0,\"computeTimeMs\":%d,\"gpuAccelerated\":false,\"embeddingPreview\":[],\"error\":\"%s\"}",
                escapeJson(msg.text()),
                System.currentTimeMillis() - startTime,
                escapeJson(e.getMessage())
            );
            getSender().tell(new ActorMessage.WorkerResult(msg.text(), errorResult), getSelf());
        }
    }

    /**
     * Generates an embedding vector using the shared ONNX session from OnnxSessionManager.
     * The session is already configured with ROCm/MIGraphX or CPU at startup.
     */
    private double[] generateEmbedding(String text) throws Exception {
        // Simple tokenization: split on whitespace, map to vocab indices via hash
        String cleanText = text.toLowerCase().replaceAll("[^a-z0-9\\s]", "").trim();
        String[] tokens = cleanText.isEmpty() ? new String[]{"unknown"} : cleanText.split("\\s+");

        int maxSeqLen = sessionManager.getMaxSequenceLength();
        int seqLen = Math.min(tokens.length + 2, maxSeqLen); // +2 for [CLS] and [SEP]
        long[][] inputIds = new long[1][seqLen];
        long[][] attentionMask = new long[1][seqLen];
        long[][] tokenTypeIds = new long[1][seqLen];

        inputIds[0][0] = 101; // [CLS]
        attentionMask[0][0] = 1;
        for (int i = 0; i < Math.min(tokens.length, seqLen - 2); i++) {
            inputIds[0][i + 1] = Math.abs(tokens[i].hashCode()) % 30521 + 100; // Map to BERT vocab range
            attentionMask[0][i + 1] = 1;
        }
        inputIds[0][seqLen - 1] = 102; // [SEP]
        attentionMask[0][seqLen - 1] = 1;

        // Run inference via the shared session manager
        try (OrtSession.Result result = sessionManager.runInference(inputIds, attentionMask, tokenTypeIds)) {
            // Extract last_hidden_state and mean pool
            OnnxTensor output = (OnnxTensor) result.get("last_hidden_state").get();
            float[][][] outputData = (float[][][]) output.getValue();

            // Mean pooling
            float[] pooled = new float[OnnxSessionManager.EMBEDDING_DIM];
            for (int i = 0; i < seqLen; i++) {
                for (int j = 0; j < OnnxSessionManager.EMBEDDING_DIM; j++) {
                    pooled[j] += outputData[0][i][j];
                }
            }
            for (int j = 0; j < OnnxSessionManager.EMBEDDING_DIM; j++) {
                pooled[j] /= seqLen;
            }

            // L2 normalize
            float norm = 0;
            for (float v : pooled) norm += v * v;
            norm = (float) Math.sqrt(norm);
            if (norm > 0) {
                for (int i = 0; i < OnnxSessionManager.EMBEDDING_DIM; i++) {
                    pooled[i] /= norm;
                }
            }

            // Convert to double[]
            double[] embedding = new double[OnnxSessionManager.EMBEDDING_DIM];
            for (int i = 0; i < OnnxSessionManager.EMBEDDING_DIM; i++) {
                embedding[i] = pooled[i];
            }

            return embedding;
        }
    }

    private String formatPreview(double[] embedding) {
        StringBuilder sb = new StringBuilder();
        int previewCount = Math.min(10, embedding.length);
        for (int i = 0; i < previewCount; i++) {
            if (i > 0) sb.append(",");
            sb.append(String.format("%.6f", embedding[i]));
        }
        return sb.toString();
    }

    private String escapeJson(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}