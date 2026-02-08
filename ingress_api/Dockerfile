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
RUN groupadd -r ingressapi && useradd -r -g ingressapi ingressapi

WORKDIR /app

# Copy the binary from builder stage
COPY --from=builder /usr/local/cargo/bin/ingress_api /usr/local/bin/ingress_api

# Change ownership to non-root user
RUN chown -R ingressapi:ingressapi /app

# Switch to non-root user
USER ingressapi

# Set environment variables
ENV RUST_LOG=info
ENV RUST_BACKTRACE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080
# Run the application
CMD ["ingress_api"]