FROM rust:slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire workspace
COPY . .

# Build both the TUI and CLI in release mode
RUN cargo build --release --workspace

# Final minimal runtime image
FROM debian:bookworm-slim

WORKDIR /app

# Install necessary runtime dependencies (e.g. CA certificates for HTTPS requests)
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy binaries from builder
COPY --from=builder /app/target/release/klintcode-tui /usr/local/bin/
COPY --from=builder /app/target/release/klintcode-cli /usr/local/bin/

# Copy skills and profiles
COPY skills /app/skills
COPY profiles /app/profiles

# Environment variables for API config
ENV KLINTCODE_ENDPOINT="http://localhost:8000"
ENV KLINTCODE_API_KEY=""

# By default, use the docker profile
ENV KLINTCODE_PROFILE="/app/profiles/docker.toml"

# Provide a workspace mount point
VOLUME ["/workspace"]

# Default entrypoint to the TUI.
# Users can run the CLI directly with `docker run ... klintcode-cli ...`
ENTRYPOINT ["klintcode-tui", "--profile", "/app/profiles/docker.toml"]
