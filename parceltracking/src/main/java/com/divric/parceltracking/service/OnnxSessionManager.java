package com.divric.parceltracking.service;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtProvider;
import ai.onnxruntime.OrtSession;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.InputStream;

/**
 * Manages the ONNX Runtime session lifecycle for the embedding model.
 * Initializes the session once at application startup with the following
 * execution provider priority:
 * <ol>
 *   <li><b>ROCm / MIGraphX</b> — AMD GPU acceleration via compiled .so libraries</li>
 *   <li><b>CPU</b> — fallback using all available threads when no GPU is present</li>
 * </ol>
 * <p>
 * The session is created once and reused for all embedding requests, avoiding
 * the overhead of model loading and provider negotiation per request.
 * </p>
 */
@Service
public class OnnxSessionManager {

    private static final Logger log = LoggerFactory.getLogger(OnnxSessionManager.class);

    /** Embedding dimension for all-MiniLM-L6-v2. */
    public static final int EMBEDDING_DIM = 384;

    /** Maximum sequence length for the transformer model. */
    private static final int MAX_SEQ_LEN = 128;

    private final OrtEnvironment env;
    private OrtSession session;
    private boolean gpuAvailable;
    private String activeProvider;

    public OnnxSessionManager() {
        this.env = OrtEnvironment.getEnvironment();
    }

    /**
     * Initializes the ONNX session at application startup.
     * Attempts ROCm/MIGraphX first, falls back to CPU if unavailable.
     */
    @PostConstruct
    public void initialize() {
        log.info("OnnxSessionManager: Initializing ONNX Runtime session...");
        long startTime = System.currentTimeMillis();

        try {
            OrtSession.SessionOptions opts = new OrtSession.SessionOptions();

            // Set CPU thread count — use all available processors as baseline
            int cpuThreads = Runtime.getRuntime().availableProcessors();
            opts.setIntraOpNumThreads(cpuThreads);
            opts.setInterOpNumThreads(Math.max(1, cpuThreads / 2));
            log.info("OnnxSessionManager: CPU thread config — intraOp: {}, interOp: {}",
                    cpuThreads, Math.max(1, cpuThreads / 2));

            // Attempt ROCm / MIGraphX execution provider
            if (tryEnableRocm(opts)) {
                gpuAvailable = true;
                activeProvider = "ROCm/MIGraphX";
                log.info("OnnxSessionManager: ROCm/MIGraphX execution provider enabled — GPU acceleration active");
            } else {
                gpuAvailable = false;
                activeProvider = "CPU";
                log.info("OnnxSessionManager: No AMD GPU detected — falling back to CPU execution with {} threads", cpuThreads);
            }

            // Load model from classpath
            InputStream modelStream = getClass().getClassLoader().getResourceAsStream("models/onnx/model.onnx");
            if (modelStream == null) {
                throw new RuntimeException("ONNX model not found on classpath: models/onnx/model.onnx");
            }
            byte[] modelBytes = modelStream.readAllBytes();
            modelStream.close();

            // Create the session (this is done once and reused)
            this.session = env.createSession(modelBytes, opts);
            opts.close();

            long elapsed = System.currentTimeMillis() - startTime;
            log.info("OnnxSessionManager: Session initialized successfully — provider: {}, model: all-MiniLM-L6-v2, "
                    + "dimensions: {}, loadTimeMs: {}",
                    activeProvider, EMBEDDING_DIM, elapsed);

        } catch (Exception e) {
            log.error("OnnxSessionManager: Failed to initialize ONNX session: {}", e.getMessage(), e);
            throw new RuntimeException("ONNX session initialization failed — application cannot start without embedding model", e);
        }
    }

    /**
     * Attempts to enable the ROCm execution provider with MIGraphX optimizations.
     * This requires the AMD ROCm libraries (libamdhip64.so, libMIGraphX.so, etc.)
     * to be available on the system library path.
     *
     * @param opts the session options to configure
     * @return true if ROCm was successfully enabled
     */
    private boolean tryEnableRocm(OrtSession.SessionOptions opts) {
        try {
            // First check if the ROCm provider is available at all
            opts.addROCM();
            log.info("OnnxSessionManager: ROCm provider registered successfully");

            // Verify by checking available providers
            java.util.EnumSet<OrtProvider> availableProviders = OrtEnvironment.getAvailableProviders();
            boolean rocmFound = false;
            for (OrtProvider provider : availableProviders) {
                log.debug("OnnxSessionManager: Available provider: {}", provider);
                if (provider.name().toUpperCase().contains("ROCM")) {
                    rocmFound = true;
                }
            }

            if (rocmFound) {
                log.info("OnnxSessionManager: ROCm confirmed in available providers list");
                return true;
            } else {
                log.warn("OnnxSessionManager: addROCM() succeeded but ROCm not in available providers — "
                        + "MIGraphX .so may be missing. Falling back to CPU.");
                return false;
            }
        } catch (OrtException e) {
            log.info("OnnxSessionManager: ROCm provider not available: {}", e.getMessage());
            return false;
        } catch (UnsatisfiedLinkError e) {
            log.info("OnnxSessionManager: ROCm native libraries not found on system: {}", e.getMessage());
            return false;
        } catch (Exception e) {
            log.warn("OnnxSessionManager: Unexpected error enabling ROCm: {}", e.getMessage());
            return false;
        }
    }

    /**
     * Runs inference on the ONNX model with the given tokenized inputs.
     *
     * @param inputIds      tokenized input IDs [1, seqLen]
     * @param attentionMask attention mask [1, seqLen]
     * @param tokenTypeIds  token type IDs [1, seqLen]
     * @return the last_hidden_state output tensor
     * @throws OrtException if inference fails
     */
    public OrtSession.Result runInference(long[][] inputIds, long[][] attentionMask, long[][] tokenTypeIds)
            throws OrtException {
        try (OnnxTensor inputTensor = OnnxTensor.createTensor(env, inputIds);
             OnnxTensor maskTensor = OnnxTensor.createTensor(env, attentionMask);
             OnnxTensor typeIdsTensor = OnnxTensor.createTensor(env, tokenTypeIds)) {

            return session.run(java.util.Map.of(
                    "input_ids", inputTensor,
                    "attention_mask", maskTensor,
                    "token_type_ids", typeIdsTensor
            ));
        }
    }

    /**
     * Returns the OrtEnvironment for creating tensors outside this manager.
     */
    public OrtEnvironment getEnvironment() {
        return env;
    }

    /**
     * Returns whether GPU (ROCm/MIGraphX) acceleration is active.
     */
    public boolean isGpuAvailable() {
        return gpuAvailable;
    }

    /**
     * Returns the name of the active execution provider.
     */
    public String getActiveProvider() {
        return activeProvider;
    }

    /**
     * Returns the maximum sequence length supported by this session.
     */
    public int getMaxSequenceLength() {
        return MAX_SEQ_LEN;
    }

    /**
     * Cleanly shuts down the ONNX session on application shutdown.
     */
    @PreDestroy
    public void shutdown() {
        if (session != null) {
            try {
                session.close();
                log.info("OnnxSessionManager: ONNX session closed");
            } catch (OrtException e) {
                log.warn("OnnxSessionManager: Error closing ONNX session: {}", e.getMessage());
            }
        }
    }
}