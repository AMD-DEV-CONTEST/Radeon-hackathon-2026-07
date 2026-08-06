# ---- Build stage ----
ARG BUILD_IMAGE=maven:3.9-eclipse-temurin-21
FROM ${BUILD_IMAGE} AS build

WORKDIR /app
COPY pom.xml .
# Download dependencies first to cache them
RUN mvn -B dependency:go-offline

# Copy source and build
COPY . .
RUN mvn -B package -DskipTests

# ---- Runtime stage ----
# Use ROCm base image with MIGraphX pre-installed for AMD GPU acceleration
# rocm/dev-ubuntu-22.04 provides: libamdhip64.so, libMIGraphX.so, librocblas.so, etc.
FROM rocm/dev-ubuntu-22.04:6.1-complete AS runtime

# Install Java 21 JRE (headless for server use) and wget for model download
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openjdk-21-jre-headless \
        ca-certificates \
        wget \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the built jar from the build stage
COPY --from=build /app/target/parceltracking-0.0.1-SNAPSHOT.jar /app/parceltracking.jar

# Create model directory and download ONNX model + tokenizer from HuggingFace
# Model: sentence-transformers/all-MiniLM-L6-v2
RUN mkdir -p /app/models/onnx && \
    wget -q --show-progress \
      -O /app/models/onnx/model.onnx \
      "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx" && \
    wget -q --show-progress \
      -O /app/models/onnx/tokenizer.json \
      "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json"

# Ensure ROCm libraries are on the library path for ONNX Runtime
# The rocm/dev-ubuntu-22.04 image installs ROCm to /opt/rocm by default
ENV LD_LIBRARY_PATH=/opt/rocm/lib:/opt/rocm/migraphx/lib:${LD_LIBRARY_PATH}
ENV PATH=/opt/rocm/bin:${PATH}

# Set ONNX Runtime to prefer ROCm/MIGraphX execution provider
# These env vars help ONNX Runtime locate the correct ROCm libraries
ENV ROCM_PATH=/opt/rocm
ENV MIGRAPHX_HOME=/opt/rocm

# Expose port
EXPOSE 8080

# Default command — the app will initialize ONNX session at startup
# OnnxSessionManager will attempt ROCm/MIGraphX first, then fall back to CPU
ENTRYPOINT ["java", "-jar", "parceltracking.jar"]