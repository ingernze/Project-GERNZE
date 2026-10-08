"""Small, serializable result types; no Tk or third-party dependencies."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class QuotaError(Exception):
    """An expected provider failure, suitable for a short user-facing status."""

    def __init__(self, message: str, status: str = "unavailable"):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Balance:
    currency: str
    total: Decimal
    topped_up: Decimal
    granted: Decimal


@dataclass(frozen=True)
class QuotaWindow:
    limit_id: str
    label: str
    lane: str
    used_percent: float
    duration_minutes: int | None
    resets_at: int | None

    @property
    def remaining_percent(self) -> float:
        return max(0.0, min(100.0, 100.0 - self.used_percent))


@dataclass(frozen=True)
class Snapshot:
    provider: str
    account_id: str  # scoped to this provider, never inferred from a window title
    account_label: str
    observed_at: float
    windows: tuple[QuotaWindow, ...] = ()
    balances: tuple[Balance, ...] = ()
    available: bool | None = None
    status: str = "ok"
    source_label: str = ""


@dataclass(frozen=True)
class Result:
    provider: str
    snapshot: Snapshot | None
    error: str | None
    status: str = "ok"


@dataclass(frozen=True)
class Alert:
    provider: str
    account_label: str
    message: str
