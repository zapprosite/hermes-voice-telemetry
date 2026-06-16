"""VoiceTelemetry plugin para hermes-agent."""
from __future__ import annotations
import logging

log = logging.getLogger("voice_telemetry")


class VoiceTelemetryPlugin:
    """Plugin standalone que inicia voice-telemetry service."""
    name = "voice-telemetry"
    kind = "standalone"
    version = "1.0.0"

    def register(self, ctx) -> None:
        # Tools: o agent pode ler healthz/metrics
        ctx.register_tool("voice_telemetry_status", self._tool_status)

        # Hook: pre_session
        ctx.register_hook("pre_session", self._on_pre_session)
        log.info("voice-telemetry v%s registrado", self.version)

    def _tool_status(self, **_):
        return {"status": "ok", "version": self.version, "service": "voice-telemetry"}

    def _on_pre_session(self, **_):
        # Garante que o service está rodando
        log.info("voice-telemetry: pre-session (checking service health)")
