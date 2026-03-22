"""Kill Switch — emergency halt all trading, optionally force-close all."""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class KillSwitch:
    """Global kill switch for the trading engine."""

    def __init__(self):
        self._active = False
        self._activated_at: datetime | None = None
        self._reason = ""

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def activated_at(self) -> datetime | None:
        return self._activated_at

    def activate(self, reason: str = "manual") -> None:
        if self._active:
            logger.info("kill switch already active")
            return
        self._active = True
        self._activated_at = datetime.now()
        self._reason = reason
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

    def deactivate(self) -> None:
        if not self._active:
            return
        logger.info("kill switch deactivated (was: %s)", self._reason)
        self._active = False
        self._reason = ""
        self._activated_at = None

    def status(self) -> dict:
        return {
            "active": self._active,
            "reason": self._reason,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
        }
