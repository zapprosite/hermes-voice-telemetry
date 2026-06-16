import time
import logging
from typing import Dict, Any

logger = logging.getLogger("hermes.voice_telemetry.circuit_breaker")

class VoiceCircuitBreaker:
    def __init__(self, redis_client, component: str, threshold_fails: int = 3, window_s: int = 60, half_open_after_s: int = 30):
        self.redis = redis_client
        self.component = component
        self.threshold_fails = threshold_fails
        self.window_s = window_s
        self.half_open_after_s = half_open_after_s
        
        self.state_key = f"hermes:telemetry:cb:{component}"
        self.open_until_key = f"hermes:telemetry:cb:open_until:{component}"
        self.fails_key = f"hermes:telemetry:cb:fails:{component}"

    def get_state(self) -> str:
        """Returns the current state: closed, open, half_open"""
        state = self.redis.get(self.state_key)
        if not state:
            self.redis.set(self.state_key, "closed")
            return "closed"
        
        state = state.decode("utf-8") if isinstance(state, bytes) else str(state)
        
        if state == "open":
            # Check if cooldown is over
            open_until = self.redis.get(self.open_until_key)
            if open_until:
                open_until = float(open_until)
                if time.time() >= open_until:
                    # Transition to half_open
                    self.redis.set(self.state_key, "half_open")
                    logger.info(f"Circuit breaker for {self.component} transitioned to half_open")
                    return "half_open"
            else:
                # If no open_until timestamp, default to transitioning to half_open
                self.redis.set(self.state_key, "half_open")
                return "half_open"
                
        return state

    def record_success(self):
        """Records a successful execution, potentially closing the breaker if half-open"""
        state = self.get_state()
        if state == "half_open":
            self.redis.set(self.state_key, "closed")
            self.redis.delete(self.fails_key)
            self.redis.delete(self.open_until_key)
            logger.info(f"Circuit breaker for {self.component} transitioned to closed (success in half_open)")
        elif state == "closed":
            # Clear historical failures occasionally or just let them expire
            self.redis.delete(self.fails_key)

    def record_failure(self):
        """Records a failure. If threshold exceeded, trips the breaker to open"""
        state = self.get_state()
        if state == "open":
            return
            
        # Add timestamp of failure
        now = time.time()
        self.redis.rpush(self.fails_key, now)
        self.redis.expire(self.fails_key, self.window_s * 2)
        
        # Clean old failures
        fails = self.redis.lrange(self.fails_key, 0, -1)
        valid_fails = []
        for f in fails:
            ft = float(f)
            if now - ft <= self.window_s:
                valid_fails.append(f)
                
        # Update list with only valid failures
        self.redis.delete(self.fails_key)
        if valid_fails:
            self.redis.rpush(self.fails_key, *valid_fails)
            self.redis.expire(self.fails_key, self.window_s * 2)
            
        # Trip if count exceeded
        if len(valid_fails) >= self.threshold_fails or state == "half_open":
            open_until = now + self.half_open_after_s
            self.redis.set(self.state_key, "open")
            self.redis.set(self.open_until_key, open_until)
            logger.warning(f"Circuit breaker for {self.component} tripped to OPEN until {open_until}")
