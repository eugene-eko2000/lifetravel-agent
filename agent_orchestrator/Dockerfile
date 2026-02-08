FROM rust:1.93-bookworm AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Cargo files first for better caching
COPY Cargo.toml ./

# Copy source code
COPY . .

# Build the application
RUN cargo install --path . -j $(nproc)

# Runtime stage
FROM debian:bookworm-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r agentorchestrator && useradd -r -g agentorchestrator agentorchestrator

WORKDIR /app

# Copy the binary from builder stage
COPY --from=builder /usr/local/cargo/bin/agent_orchestrator /usr/local/bin/agent_orchestrator

# Change ownership to non-root user
RUN chown -R agentorchestrator:agentorchestrator /app

# Switch to non-root user
USER agentorchestrator

# Set environment variables
ENV RUST_LOG=info
ENV RUST_BACKTRACE=1

EXPOSE 8080
# Run the application
CMD ["agent_orchestrator"]