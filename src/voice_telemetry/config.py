"""Voice telemetry config (Pydantic)."""
from pathlib import Path
from pydantic import BaseSettings, Field


class TelemetryConfig(BaseSettings):
    port: int = 4140
    bind: str = "127.0.0.1"
    log_path: Path = Field(default=Path("/var/log/voice-telemetry.log"))
    cb_threshold_fails: int = 3
    cb_window_s: int = 60
    cb_half_open_after_s: int = 30
    rolling_window: int = 100
