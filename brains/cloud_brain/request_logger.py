"""
cloud_brain/request_logger.py
================================
Request Logger

Records structured information about every cloud request attempt.

Fields recorded per attempt
---------------------------
- provider          : provider_id used
- model             : model_id used
- token_estimate    : max_tokens from the estimator
- actual_tokens     : max_tokens actually sent to the provider
- attempt_number    : 1-based attempt counter
- request_passed    : whether RequestValidator passed
- response_passed   : whether ResponseValidator passed
- retry_status      : RetryStatus for this attempt
- validation_issues : list of validation issue summaries
- timestamp_utc     : ISO-8601 UTC timestamp
- latency_ms        : optional round-trip latency

Records are kept in memory (a bounded deque) and emitted to the standard
Python logging system.

Design principles
-----------------
- Stdlib only. No I/O. No LLM calls.
- Never raises on malformed input — logs what it can.
- The in-memory log is bounded by LoggerConfig.max_records.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Log level
# ---------------------------------------------------------------------------

class LogLevel(str, Enum):
    DEBUG   = "debug"
    INFO    = "info"
    WARNING = "warning"
    ERROR   = "error"


# ---------------------------------------------------------------------------
# Request record
# ---------------------------------------------------------------------------

@dataclass
class RequestRecord:
    """
    Structured log entry for one cloud request attempt.

    Attributes
    ----------
    record_id : str
        Auto-generated UUID for this record.
    provider : str
        Provider ID used.
    model : str
        Model ID used.
    token_estimate : int
        max_tokens from the estimator before any adjustment.
    actual_tokens : int
        max_tokens actually passed to the provider.
    attempt_number : int
        1-based attempt counter.
    request_passed : bool
        Whether RequestValidator.validate() returned passed=True.
    response_passed : bool
        Whether ResponseValidator.validate() returned passed=True.
    retry_status : str
        RetryStatus value for this attempt.
    validation_issues : List[str]
        Summaries of every ValidationIssue / AxisResult failure.
    timestamp_utc : str
        ISO-8601 UTC timestamp at record creation.
    latency_ms : Optional[float]
        Round-trip latency if measured by the caller.
    extra : Dict[str, Any]
        Any additional key-value metadata the caller wants to attach.
    """
    record_id: str
    provider: str
    model: str
    token_estimate: int
    actual_tokens: int
    attempt_number: int
    request_passed: bool
    response_passed: bool
    retry_status: str
    validation_issues: List[str] = field(default_factory=list)
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    latency_ms: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "provider": self.provider,
            "model": self.model,
            "token_estimate": self.token_estimate,
            "actual_tokens": self.actual_tokens,
            "attempt_number": self.attempt_number,
            "request_passed": self.request_passed,
            "response_passed": self.response_passed,
            "retry_status": self.retry_status,
            "validation_issues": list(self.validation_issues),
            "timestamp_utc": self.timestamp_utc,
            "latency_ms": self.latency_ms,
            "extra": dict(self.extra),
        }

    @property
    def overall_success(self) -> bool:
        """True when both request and response validation passed."""
        return self.request_passed and self.response_passed


# ---------------------------------------------------------------------------
# Logger configuration
# ---------------------------------------------------------------------------

@dataclass
class LoggerConfig:
    """
    Configuration for the RequestLogger.

    Attributes
    ----------
    max_records : int
        Maximum number of records kept in memory (rolling buffer).
    emit_level : LogLevel
        Minimum Python logging level for emitting records.
    include_issues_in_log : bool
        When True, validation issues are included in the log message.
    """
    max_records: int           = 500
    emit_level: LogLevel       = LogLevel.INFO
    include_issues_in_log: bool = True


# ---------------------------------------------------------------------------
# Request Logger
# ---------------------------------------------------------------------------

class RequestLogger:
    """
    Structured logger for Adaptive Cloud Brain request/response cycles.

    Usage
    -----
    ::

        req_logger = RequestLogger()

        record = req_logger.record(
            provider="openrouter",
            model="deepseek/deepseek-v4-flash-0731",
            token_estimate=512,
            actual_tokens=512,
            attempt_number=1,
            request_passed=True,
            response_passed=False,
            retry_status="retry",
            validation_issues=["empty_response: Response is None."],
            latency_ms=320.5,
        )

        # Access recent history
        history = req_logger.recent(n=10)
        stats   = req_logger.summary_stats()
    """

    def __init__(self, config: Optional[LoggerConfig] = None) -> None:
        self._config: LoggerConfig = config or LoggerConfig()
        self._records: Deque[RequestRecord] = deque(maxlen=self._config.max_records)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        provider: str,
        model: str,
        token_estimate: int,
        actual_tokens: int,
        attempt_number: int,
        request_passed: bool,
        response_passed: bool,
        retry_status: str,
        validation_issues: Optional[List[str]] = None,
        latency_ms: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> RequestRecord:
        """
        Create and store a RequestRecord.

        Returns the created record so the caller can reference it.
        """
        rec = RequestRecord(
            record_id=uuid.uuid4().hex[:12],
            provider=provider,
            model=model,
            token_estimate=token_estimate,
            actual_tokens=actual_tokens,
            attempt_number=attempt_number,
            request_passed=request_passed,
            response_passed=response_passed,
            retry_status=retry_status,
            validation_issues=list(validation_issues or []),
            latency_ms=latency_ms,
            extra=dict(extra or {}),
        )
        self._records.append(rec)
        self._emit(rec)
        return rec

    def recent(self, n: int = 20) -> List[RequestRecord]:
        """Return the ``n`` most recent records (newest last)."""
        records = list(self._records)
        return records[-n:]

    def all_records(self) -> List[RequestRecord]:
        """Return all records in the in-memory buffer (oldest first)."""
        return list(self._records)

    def clear(self) -> None:
        """Flush the in-memory record buffer."""
        self._records.clear()

    def summary_stats(self) -> Dict[str, Any]:
        """
        Return aggregate statistics over all records in memory.

        Keys: total_attempts, successful, failed, retried,
              avg_latency_ms, providers (dict of provider → count).
        """
        records = list(self._records)
        if not records:
            return {
                "total_attempts": 0,
                "successful": 0,
                "failed": 0,
                "retried": 0,
                "avg_latency_ms": None,
                "providers": {},
            }

        successful = sum(1 for r in records if r.overall_success)
        failed     = sum(1 for r in records if not r.overall_success)
        retried    = sum(1 for r in records if r.retry_status == "retry")

        latencies = [r.latency_ms for r in records if r.latency_ms is not None]
        avg_latency = (sum(latencies) / len(latencies)) if latencies else None

        providers: Dict[str, int] = {}
        for r in records:
            providers[r.provider] = providers.get(r.provider, 0) + 1

        return {
            "total_attempts": len(records),
            "successful": successful,
            "failed": failed,
            "retried": retried,
            "avg_latency_ms": round(avg_latency, 2) if avg_latency is not None else None,
            "providers": providers,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit(self, rec: RequestRecord) -> None:
        """Emit the record to the Python logging system."""
        level_map = {
            LogLevel.DEBUG:   logging.DEBUG,
            LogLevel.INFO:    logging.INFO,
            LogLevel.WARNING: logging.WARNING,
            LogLevel.ERROR:   logging.ERROR,
        }
        level = level_map.get(self._config.emit_level, logging.INFO)

        status = "✓" if rec.overall_success else "✗"
        msg = (
            f"[CloudBrain] {status} provider={rec.provider} model={rec.model} "
            f"attempt={rec.attempt_number}/{rec.request_passed and rec.response_passed} "
            f"tokens=estimate:{rec.token_estimate}/actual:{rec.actual_tokens} "
            f"retry={rec.retry_status}"
        )
        if rec.latency_ms is not None:
            msg += f" latency={rec.latency_ms:.1f}ms"

        if self._config.include_issues_in_log and rec.validation_issues:
            msg += f" issues={rec.validation_issues}"

        logger.log(level, msg)
