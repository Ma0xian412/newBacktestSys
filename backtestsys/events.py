from dataclasses import dataclass
from enum import Enum
from typing import Optional


class EventType(str, Enum):
    SNAPSHOT_RECV = "snapshot_recv"
    ORDER_ARRIVE_EXCH = "order_arrive_exch"
    CANCEL_ARRIVE_EXCH = "cancel_arrive_exch"
    EXEC_REPORT_RECV = "exec_report_recv"
    CANCEL_ACK_RECV = "cancel_ack_recv"
    INTERVAL_END = "interval_end"


@dataclass(frozen=True)
class Event:
    time: float
    event_type: EventType
    order_id: Optional[str] = None
    fill_qty: float = 0.0
    fill_px: Optional[float] = None
    exchtime: Optional[float] = None
    recvtime: Optional[float] = None
    status: Optional[str] = None
