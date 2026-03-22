"""Enums shared across research and execution layers."""

from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILLED = "PARTIAL_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


class RiskAction(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"
    REDUCE = "REDUCE"       # downsize qty
    WARN = "WARN"           # pass with warning


class AuditAction(str, Enum):
    ORDER_SUBMIT = "ORDER_SUBMIT"
    ORDER_CANCEL = "ORDER_CANCEL"
    ORDER_FILL = "ORDER_FILL"
    ORDER_REJECT = "ORDER_REJECT"
    RISK_BLOCK = "RISK_BLOCK"
    RISK_WARN = "RISK_WARN"
    KILL_SWITCH_ON = "KILL_SWITCH_ON"
    KILL_SWITCH_OFF = "KILL_SWITCH_OFF"
    SETTLEMENT = "SETTLEMENT"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    BACKTEST_FILTER = "BACKTEST_FILTER"


class FilterReason(str, Enum):
    """Why a backtest signal was rejected by the credibility filter."""
    UP_LIMIT = "UP_LIMIT"
    DOWN_LIMIT = "DOWN_LIMIT"
    ONE_BOARD = "ONE_BOARD"
    SUSPENDED = "SUSPENDED"
    ST_LIMIT = "ST_LIMIT"
    IPO_FIRST_DAY = "IPO_FIRST_DAY"
    VOLUME_CAP = "VOLUME_CAP"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"


class PromotionLevel(int, Enum):
    """Strategy promotion pipeline levels."""
    RESEARCH = 0
    BACKTEST_PASSED = 1
    OUT_OF_SAMPLE = 2
    PAPER_TRADING = 3
    SMALL_LIVE = 4
    FULL_LIVE = 5


class StrategyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"
