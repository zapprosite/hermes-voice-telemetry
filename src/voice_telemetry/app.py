import os
import sys
import time
import subprocess
import asyncio
import redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi import FastAPI, Response, Request
from typing import Dict, Any

# Add homelab-context modules to path to import healthcheck and config
sys.path.insert(0, "/home/will/workspace/homelab-context/modules")

try:
    from hermes_voice.config import HermesVoiceConfig
    from hermes_voice.healthcheck import (
        _check_gpu,
        _check_redis,
        _check_stt_policy,
        _check_omnivoice,
        _check_llm_primary,
        _check_litellm,
    )
except ImportError:
    # Fallback placeholders in case paths aren't fully set up during build/init
    HermesVoiceConfig = None

from circuit_breaker import VoiceCircuitBreaker
from metrics_collector import get_latency_percentiles
from structured_logger import StructuredLogger

logger_sre = StructuredLogger(os.getenv("VOICE_TELEMETRY_LOG_PATH", "/home/will/.hermes/logs/voice-telemetry.log"))



class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adiciona HTTP security headers (state da arte 2026)."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


app = FastAPI(title="Hermes Voice Telemetry")

# Connect to Redis
redis_client = redis.Redis(host="127.0.0.1", port=6379, decode_responses=False)

# Background task to monitor GPU and manage circuit breaker state
gpu_consecutive_over_limit = 0

async def monitor_gpu_vram():
    global gpu_consecutive_over_limit
    cb_gpu = VoiceCircuitBreaker(redis_client, "gpu", threshold_fails=3, window_s=60, half_open_after_s=30)
    
    # Read thresholds from env/config
    gpu_threshold_pct = float(os.getenv("VOICE_CB_GPU_VRAM_PCT", "95"))
    
    while True:
        try:
            # Check GPU VRAM via nvidia-smi
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                lines = result.stdout.strip().splitlines()
                if lines:
                    used, total = map(float, lines[0].split(","))
                    used_pct = (used / total) * 100.0
                    
                    if used_pct > gpu_threshold_pct:
                        gpu_consecutive_over_limit += 1
                        if gpu_consecutive_over_limit >= 10:
                            # 10s consecutive
                            cb_gpu.record_failure()
                            # Reset counter so we don't spam
                            gpu_consecutive_over_limit = 0
                    else:
                        gpu_consecutive_over_limit = 0
                        cb_gpu.record_success()
            else:
                gpu_consecutive_over_limit = 0
        except Exception:
            gpu_consecutive_over_limit = 0
            
        await asyncio.sleep(1.0)

@app.on_event("startup")
def startup_event():
    asyncio.create_task(monitor_gpu_vram())

@app.post("/internal/metric")
async def post_internal_metric(request: Request):
    try:
        data = await request.json()
    except Exception:
        return Response(content='{"status": "error", "message": "invalid json"}', media_type="application/json", status_code=400)

    event_type = data.get("type") or data.get("event") or "metric"
    component = data.get("component")
    
    # 1. Structured Logging (non-blocking)
    logger_sre.log(event_type, **data)
    
    # 2. Redis Telemetry updates
    if event_type in ("wake_hit", "wake_detected"):
        redis_client.incr("hermes:telemetry:wake:total")
        
    elif component:
        duration_ms = data.get("duration_ms")
        success = data.get("success", True)
        
        # Latency
        if duration_ms is not None:
            from metrics_collector import push_latency
            rolling_window = int(os.getenv("VOICE_TELEMETRY_ROLLING_WINDOW", "100"))
            push_latency(redis_client, component, float(duration_ms), window_size=rolling_window)
            
        # Circuit Breaker state & error counters
        cb = VoiceCircuitBreaker(redis_client, component)
        if success:
            cb.record_success()
        else:
            cb.record_failure()
            redis_client.incr(f"hermes:telemetry:errors:{component}")

    return {"status": "ok"}

app.add_middleware(SecurityHeadersMiddleware)

@app.get("/healthz")
def get_healthz():
    # Read current state
    config = HermesVoiceConfig.from_env() if HermesVoiceConfig else None
    
    checks = {}
    
    # 1. Redis
    redis_ok = False
    redis_detail = ""
    try:
        ping_res = redis_client.ping()
        redis_ok = bool(ping_res)
        redis_detail = "pong" if redis_ok else "no pong"
    except Exception as e:
        redis_detail = str(e)
    checks["redis"] = {"ok": redis_ok, "detail": redis_detail}
    
    # 2. GPU
    gpu_ok = False
    gpu_detail = ""
    if redis_ok:
        try:
            gpu_check = _check_gpu()
            gpu_ok = gpu_check.ok
            gpu_detail = gpu_check.detail or f"GPUS: {gpu_check.data.get('gpus', [])}"
        except Exception as e:
            gpu_detail = str(e)
    checks["gpu"] = {"ok": gpu_ok, "detail": gpu_detail}
    
    # 3. Mic
    mic_ok = False
    mic_detail = ""
    if redis_ok:
        try:
            headless_client_alive = redis_client.hget("hermes:voice:state", "headless_client_alive")
            if headless_client_alive:
                headless_client_alive = headless_client_alive.decode("utf-8")
            mic_ok = (headless_client_alive in ("1", "true", "yes"))
            mic_detail = "headless_client active" if mic_ok else "headless_client offline/inactive"
        except Exception as e:
            mic_detail = str(e)
    checks["mic"] = {"ok": mic_ok, "detail": mic_detail}
    
    # 4. Wake
    wake_ok = False
    wake_detail = ""
    if redis_ok:
        try:
            wake_model_loaded = redis_client.hget("hermes:voice:state", "wake_model_loaded")
            if wake_model_loaded:
                wake_model_loaded = wake_model_loaded.decode("utf-8")
            wake_ok = (wake_model_loaded in ("1", "true", "yes"))
            wake_model = redis_client.hget("hermes:voice:state", "wake_model")
            if wake_model:
                wake_model = wake_model.decode("utf-8")
            wake_detail = f"model: {wake_model or 'unknown'}" if wake_ok else "wake model not loaded"
        except Exception as e:
            wake_detail = str(e)
    checks["wake"] = {"ok": wake_ok, "detail": wake_detail}

    # 5. VAD
    vad_ok = False
    vad_detail = ""
    if redis_ok:
        try:
            # Check if livekit session is connected / running
            agent_connected = redis_client.hget("hermes:voice:state", "agent_connected")
            if agent_connected:
                agent_connected = agent_connected.decode("utf-8")
            vad_ok = (agent_connected in ("1", "true", "yes"))
            vad_detail = "LiveKit agent connected and VAD active" if vad_ok else "LiveKit agent offline"
        except Exception as e:
            vad_detail = str(e)
    checks["vad"] = {"ok": vad_ok, "detail": vad_detail}

    # 6. STT
    stt_ok = False
    stt_detail = ""
    if config:
        try:
            stt_check = _check_stt_policy(config)
            stt_ok = stt_check.ok
            stt_detail = stt_check.detail or f"STT Model: {config.stt_model}"
        except Exception as e:
            stt_detail = str(e)
    checks["stt"] = {"ok": stt_ok, "detail": stt_detail}

    # 7. LLM T1
    llm_t1_ok = False
    llm_t1_detail = ""
    if config:
        try:
            llm_t1_check = _check_llm_primary(config)
            llm_t1_ok = llm_t1_check.ok
            llm_t1_detail = llm_t1_check.detail or f"T1 Model: {config.llm_primary_model}"
        except Exception as e:
            llm_t1_detail = str(e)
    checks["llm_t1"] = {"ok": llm_t1_ok, "detail": llm_t1_detail}

    # 8. LLM T2
    llm_t2_ok = False
    llm_t2_detail = ""
    if config:
        try:
            llm_t2_check = _check_litellm(config)
            llm_t2_ok = llm_t2_check.ok
            llm_t2_detail = llm_t2_check.detail or f"T2 Model: {config.llm_model}"
        except Exception as e:
            llm_t2_detail = str(e)
    checks["llm_t2"] = {"ok": llm_t2_ok, "detail": llm_t2_detail}

    # 9. TTS
    tts_ok = False
    tts_detail = ""
    if config:
        try:
            tts_check = _check_omnivoice(config)
            tts_ok = tts_check.ok
            tts_detail = tts_check.detail or f"TTS Voice: {config.omnivoice_voice}"
        except Exception as e:
            tts_detail = str(e)
    checks["tts"] = {"ok": tts_ok, "detail": tts_detail}

    # 10. Circuit Breaker
    cb_ok = True
    cb_details = {}
    for comp in ["stt", "tts", "gpu"]:
        cb = VoiceCircuitBreaker(redis_client, comp)
        state = cb.get_state()
        cb_details[comp] = state
        if state == "open":
            cb_ok = False
    checks["circuit_breaker"] = {"ok": cb_ok, "detail": f"Breakers: {cb_details}"}

    # 11. P95 latency check
    p95_ok = True
    p95_details = {}
    # SRE Targets:
    # stt_duration_seconds: max 300ms (0.3s) Whisper transcription latency?
    # llm_duration_seconds: T1 < 300ms? Wait, let's keep check simple
    # total_e2e: < 1500ms
    targets = {
        "stt": 500.0,      # ms
        "llm:t1": 300.0,   # ms
        "tts": 600.0,      # ms
        "e2e": 1500.0,     # ms
    }
    for comp, target in targets.items():
        pct = get_latency_percentiles(redis_client, comp)
        p95_val = pct["p95"]
        p95_details[comp] = f"{p95_val:.1f}ms"
        # If we have samples, and p95 exceeds target, warn/fail
        if pct["count"] > 0 and p95_val > target:
            p95_ok = False
    checks["p95"] = {"ok": p95_ok, "detail": f"P95: {p95_details} (Targets: {targets})"}

    # Overall health
    overall_ok = all(c["ok"] for c in checks.values())
    import json
    return Response(
        content=json.dumps({
            "status": "ok" if overall_ok else "degraded",
            "checks": checks
        }),
        media_type="application/json",
        status_code=200 if overall_ok else 503
    )

app.add_middleware(SecurityHeadersMiddleware)

@app.get("/metrics")
def get_metrics():
    # Return Prometheus metrics
    lines = []
    
    # 1. hermes_voice_wake_total{result="hit|miss"}
    wake_total_hit = int(redis_client.get("hermes:telemetry:wake:total") or 0)
    lines.append(f'hermes_voice_wake_total{{result="hit"}} {wake_total_hit}')
    lines.append(f'hermes_voice_wake_total{{result="miss"}} 0')  # miss is default 0
    
    # Latencies
    for comp in ["stt", "llm:t1", "llm:t2", "tts", "e2e"]:
        pct = get_latency_percentiles(redis_client, comp)
        lines.append(f'hermes_voice_{comp.replace(":", "_")}_duration_seconds {pct["p50"] / 1000.0}')
        
    # Circuit breaker states
    for comp in ["stt", "tts", "gpu"]:
        cb = VoiceCircuitBreaker(redis_client, comp)
        state = cb.get_state()
        val = 0
        if state == "closed":
            val = 0
        elif state == "half_open":
            val = 1
        elif state == "open":
            val = 2
        lines.append(f'hermes_voice_circuit_breaker_state{{component="{comp}"}} {val}')
        
    # Errors
    for comp in ["stt", "tts", "gpu"]:
        errors = int(redis_client.get(f"hermes:telemetry:errors:{comp}") or 0)
        lines.append(f'hermes_voice_errors_total{{component="{comp}"}} {errors}')
        
    return Response(content="\n".join(lines) + "\n", media_type="text/plain")
