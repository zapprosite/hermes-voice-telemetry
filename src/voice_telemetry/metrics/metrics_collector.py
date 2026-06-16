import math
from typing import Dict, Any, List

def push_latency(redis_client, component: str, duration_ms: float, window_size: int = 100):
    """Pushes a latency sample to the rolling window in Redis."""
    key = f"hermes:telemetry:{component}:duration_ms"
    # LPUSH then LTRIM to keep only the latest window_size samples
    redis_client.lpush(key, f"{duration_ms:.2f}")
    redis_client.ltrim(key, 0, window_size - 1)

def get_latency_percentiles(redis_client, component: str) -> Dict[str, float]:
    """Calculates percentiles (p50, p95, p99) for a component from Redis."""
    key = f"hermes:telemetry:{component}:duration_ms"
    samples_raw = redis_client.lrange(key, 0, -1)
    if not samples_raw:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}
        
    samples = sorted([float(s) for s in samples_raw])
    n = len(samples)
    
    def percentile(p: float) -> float:
        if n == 0:
            return 0.0
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return samples[int(k)]
        return samples[f] * (c - k) + samples[c] * (k - f)
        
    return {
        "p50": percentile(0.5),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "count": n
    }
