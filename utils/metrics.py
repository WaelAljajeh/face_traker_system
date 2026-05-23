# ============================================================
# PERFORMANCE METRICS AND PROFILING
# ============================================================

import time
from typing import Dict, List
from collections import deque


class Metrics:
    """Track performance metrics with rolling averages."""
    
    def __init__(self, window_size: int = 30):
        self.window_size = window_size
        self.timers: Dict[str, deque] = {}
        self.counters: Dict[str, int] = {}
        self.start_times: Dict[str, float] = {}
    
    def start_timer(self, name: str):
        """Start a named timer."""
        self.start_times[name] = time.time()
    
    def end_timer(self, name: str) -> float:
        """End timer and record elapsed time (ms)."""
        if name not in self.start_times:
            return 0.0
        
        elapsed = (time.time() - self.start_times[name]) * 1000  # Convert to ms
        
        if name not in self.timers:
            self.timers[name] = deque(maxlen=self.window_size)
        
        self.timers[name].append(elapsed)
        return elapsed
    
    def get_average_time(self, name: str) -> float:
        """Get average time for a timer (ms)."""
        if name not in self.timers or not self.timers[name]:
            return 0.0
        return sum(self.timers[name]) / len(self.timers[name])
    
    def get_max_time(self, name: str) -> float:
        """Get max time for a timer."""
        if name not in self.timers or not self.timers[name]:
            return 0.0
        return max(self.timers[name])
    
    def increment(self, name: str, value: int = 1):
        """Increment a counter."""
        self.counters[name] = self.counters.get(name, 0) + value
    
    def get_counter(self, name: str) -> int:
        """Get counter value."""
        return self.counters.get(name, 0)
    
    def reset_counter(self, name: str):
        """Reset counter."""
        self.counters[name] = 0
    
    def get_summary(self) -> Dict:
        """Get performance summary."""
        summary = {}
        
        # Timing summary
        for name, times in self.timers.items():
            if times:
                summary[f"{name}_avg_ms"] = self.get_average_time(name)
                summary[f"{name}_max_ms"] = self.get_max_time(name)
        
        # Counter summary
        for name, value in self.counters.items():
            summary[f"{name}_count"] = value
        
        return summary
    
    def log_summary(self, logger):
        """Log performance summary."""
        summary = self.get_summary()
        logger.info("=== PERFORMANCE METRICS ===")
        for key, value in summary.items():
            if isinstance(value, float):
                logger.info(f"{key}: {value:.2f}")
            else:
                logger.info(f"{key}: {value}")


# Global metrics instance
_metrics_instance = None


def get_metrics() -> Metrics:
    """Get global metrics instance."""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = Metrics()
    return _metrics_instance
