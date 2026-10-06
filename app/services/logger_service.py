"""Backward-compatible shim: telemetry formatting lives in activity_logger.

Use `from app.services.activity_logger import TelemetryLogger, clean_line`.
"""
from app.services.activity_logger import TelemetryLogger, clean_line

__all__ = ["TelemetryLogger", "clean_line"]
