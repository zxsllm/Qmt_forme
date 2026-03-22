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
