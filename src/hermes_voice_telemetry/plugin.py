"""VoiceTelemetryPlugin: hermes-voice-telemetry para hermes-agent."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("hermes-voice-telemetry")


class VoiceTelemetryPlugin:
    """Plugin standalone."""
    name = "hermes-voice-telemetry"
    kind = "standalone"
    version = "1.0.0"

    def register(self, ctx) -> None:
        """Hook de registro."""
        # Tools
        ctx.register_tool("hermes_voice_telemetry_status", self._tool_status)

        # Skills
        skill_path = self._skill_path()
        if skill_path.exists():
            ctx.register_skill("hermes-voice-telemetry", skill_path)

        log.info("hermes-voice-telemetry v%s registrado", self.version)

    def _skill_path(self) -> Path:
        return Path(__file__).parent.parent.parent / "skills" / "voice-telemetry"

    def _tool_status(self, **_):
        return {"status": "ready", "version": self.version}
