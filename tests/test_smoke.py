"""Smoke tests para hermes-voice-telemetry."""
import pytest
import httpx


def test_healthz_reachable():
    """/healthz deve responder (se servico rodando)."""
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get("http://127.0.0.1:4140/healthz")
            # 200 ou 503 (saudavel ou unhealthy) sao ok
            assert r.status_code in (200, 503)
            body = r.json()
            assert "checks" in body
    except httpx.ConnectError:
        pytest.skip("voice-telemetry nao esta rodando (esperado em CI)")


def test_metrics_endpoint():
    """/metrics deve retornar Prometheus format."""
    try:
        import httpx
        with httpx.Client(timeout=2.0) as c:
            r = c.get("http://127.0.0.1:4140/metrics")
            assert r.status_code == 200
            assert "wake_detections_total" in r.text or "python_info" in r.text
    except httpx.ConnectError:
        pytest.skip("voice-telemetry nao esta rodando")


def test_app_imports():
    """FastAPI app deve ser importavel."""
    try:
        from voice_telemetry.app import app
        assert app.title is not None
    except ImportError:
        pytest.skip("voice_telemetry nao instalado")
