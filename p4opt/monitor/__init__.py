"""Runtime degradation, slow-test, and flaky-test detection."""
from p4opt.monitor.degradation import (
    detect_degrading,
    detect_slow,
    detect_flaky,
    HealthReport,
)

__all__ = ["detect_degrading", "detect_slow", "detect_flaky", "HealthReport"]
