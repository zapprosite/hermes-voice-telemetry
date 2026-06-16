import os
import json
import time
import queue
import threading
import sys
from datetime import datetime, timezone
from typing import Dict, Any

class StructuredLogger:
    def __init__(self, log_path: str = "/home/will/.hermes/logs/voice-telemetry.log"):
        self.log_path = log_path
        self.queue = queue.Queue()
        self.running = True
        
        # Ensure log directory exists
        log_dir = os.path.dirname(self.log_path)
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            print(f"Error creating log directory {log_dir}: {e}", file=sys.stderr)
            
        self.thread = threading.Thread(target=self._drain_loop, daemon=True)
        self.thread.start()

    def log(self, event: str, **kwargs):
        """Queue a log event to be written in JSON format."""
        if not self.running:
            return
            
        log_data = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "event": event,
        }
        log_data.update(kwargs)
        self.queue.put(log_data)

    def _drain_loop(self):
        while self.running or not self.queue.empty():
            try:
                try:
                    log_data = self.queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                log_line = json.dumps(log_data)
                
                # Write to stdout
                print(log_line, flush=True)
                
                # Write to file
                try:
                    with open(self.log_path, "a") as f:
                        f.write(log_line + "\n")
                except Exception as e:
                    print(f"Error writing to log file {self.log_path}: {e}", file=sys.stderr)
                    
                self.queue.task_done()
            except Exception as e:
                print(f"Error in logger drain loop: {e}", file=sys.stderr)

    def shutdown(self):
        self.running = False
        if self.thread.is_alive():
            self.thread.join(timeout=2.0)
