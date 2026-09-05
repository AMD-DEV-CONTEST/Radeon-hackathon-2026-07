FROM rust:slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire workspace
COPY . .

# Install the exact TeaQL compiler version required by the agent workflow.
RUN cargo install cargo-teaql --version 2.0.8 --locked

# Build both the TUI and CLI in release mode
RUN cargo build --release -p klintcode-tui -p klintcode-cli

# The runtime intentionally retains Rust and Cargo because M5 generates and
# compiler-checks a Rust workspace inside the container.
FROM rust:slim

WORKDIR /app

# Install necessary runtime dependencies (e.g. CA certificates for HTTPS requests)
RUN apt-get update && apt-get install -y \
    ca-certificates \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy binaries from builder
COPY --from=builder /app/target/release/klintcode-tui /usr/local/bin/
COPY --from=builder /app/target/release/klintcode /usr/local/bin/
COPY --from=builder /usr/local/cargo/bin/cargo-teaql /usr/local/cargo/bin/

# Install cargo subcommand links used by generated TeaQL projects.
RUN cargo-teaql install-links

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
# Users can run the CLI with `docker run --entrypoint klintcode ...`.
ENTRYPOINT ["klintcode-tui", "--profile", "/app/profiles/docker.toml"]
