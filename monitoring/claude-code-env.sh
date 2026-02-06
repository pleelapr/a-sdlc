# Claude Code Monitoring Configuration
# Source this file in your shell profile (~/.zshrc or ~/.bashrc):
#   source /path/to/monitoring/claude-code-env.sh

# ── Langfuse (conversation tracing) ──────────────────────────────────────
# These are Langfuse-specific env vars and won't interfere with other tools.
# After first Langfuse login at http://localhost:13000, create a project
# and paste the API keys here.
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_HOST="http://localhost:13000"

# ── OpenTelemetry (scoped to claude process only) ────────────────────────
# Wraps the `claude` command so OTEL vars are set only for that process.
# Docker, Python, Node, etc. will NOT inherit these variables.

# Optional: Include user prompt content (disabled by default for privacy)
# Uncomment inside the function below if desired:
#   OTEL_LOG_USER_PROMPTS=1

# Optional: Custom resource attributes for filtering
# Uncomment inside the function below if desired:
#   OTEL_RESOURCE_ATTRIBUTES="user.name=pleelaprachakul,environment=personal"

# Optional: Shorter export intervals for debugging (defaults: metrics=60s, logs=5s)
# Uncomment inside the function below if desired:
#   OTEL_METRIC_EXPORT_INTERVAL=10000
#   OTEL_LOGS_EXPORT_INTERVAL=5000

claude() {
  CLAUDE_CODE_ENABLE_TELEMETRY=1 \
  OTEL_METRICS_EXPORTER=otlp \
  OTEL_LOGS_EXPORTER=otlp \
  OTEL_EXPORTER_OTLP_PROTOCOL=grpc \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
  OTEL_LOG_TOOL_DETAILS=1 \
  command claude "$@"
}
