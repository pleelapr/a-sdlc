# Claude Code OpenTelemetry Configuration
# Source this file in your shell profile (~/.zshrc or ~/.bashrc):
#   source /path/to/monitoring/claude-code-env.sh
#
# Or append it:
#   cat /path/to/monitoring/claude-code-env.sh >> ~/.zshrc

# Enable telemetry collection
export CLAUDE_CODE_ENABLE_TELEMETRY=1

# Export both metrics and events/logs via OTLP
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp

# OTLP endpoint (SigNoz OTel Collector)
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Include MCP tool names and skill names in events
export OTEL_LOG_TOOL_DETAILS=1

# Optional: Include user prompt content (disabled by default for privacy)
# export OTEL_LOG_USER_PROMPTS=1

# Optional: Custom resource attributes for filtering
# export OTEL_RESOURCE_ATTRIBUTES="user.name=pleelaprachakul,environment=personal"

# Optional: Shorter export intervals for debugging (defaults: metrics=60s, logs=5s)
# export OTEL_METRIC_EXPORT_INTERVAL=10000
# export OTEL_LOGS_EXPORT_INTERVAL=5000
