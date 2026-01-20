from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"


class OrderStatus(str, Enum):
    LIVE = "LIVE"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


@dataclass
class Fill:
    qty: float
    px: float
    exchtime: float
    recvtime: float


@dataclass
class Order:
    order_id: str
    side: OrderSide
    px: float
    qty: float
    tif: TimeInForce = TimeInForce.GTC
    recv_send_time: float = 0.0
    exchtime_arrive: Optional[float] = None
    status: OrderStatus = OrderStatus.LIVE
    filled_qty: float = 0.0
    fills: List[Fill] = field(default_factory=list)
    pos: Optional[float] = None

    @property
    def remaining(self) -> float:
        return max(0.0, self.qty - self.filled_qty)
