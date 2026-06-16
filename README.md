# hermes-voice-telemetry

**Voice-telemetry service (FastAPI + circuit breaker + Prometheus metrics) para hermes-agent v0.16+.**

## Install

```bash
pip install hermes-voice-telemetry
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | 11 checks (gpu, mic, wake, vad, stt, llm_t1, llm_t2, tts, redis, cb, p95) |
| GET | `/metrics` | Prometheus format |
| POST | `/internal/metric` | Fire-and-forget from runtime |

## Systemd

```bash
mkdir -p ~/.config/systemd/user/
cp systemd/user/voice-telemetry.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now voice-telemetry.service
```

## Compatibilidade

- Python 3.11+
- Bind 127.0.0.1 only (port 4140)
- Ubuntu 22.04+

## License

MIT
