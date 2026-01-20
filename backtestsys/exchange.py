from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .config import SimulationConfig
from .events import Event, EventType
from .orders import Fill, Order, OrderSide, OrderStatus, TimeInForce
from .tape import EventTape
from .time import TimeMapper


@dataclass
class ExchangeDiagnostics:
    negative_queue_prices: List[float] = field(default_factory=list)


class ShadowOrderBook:
    def __init__(self) -> None:
        self.orders: Dict[str, Order] = {}

    def live_orders(self) -> Iterable[Order]:
        return (order for order in self.orders.values() if order.status in {OrderStatus.LIVE, OrderStatus.PARTIAL})

    def shadow_remaining(self, side: OrderSide, price: float) -> float:
        return sum(order.remaining for order in self.live_orders() if order.side == side and order.px == price)

    def add(self, order: Order) -> None:
        self.orders[order.order_id] = order

    def get(self, order_id: str) -> Optional[Order]:
        return self.orders.get(order_id)


class ExchangeSimulator:
    def __init__(self, tape: EventTape, config: SimulationConfig, mapper: TimeMapper) -> None:
        self.tape = tape
        self.config = config
        self.mapper = mapper
        self.book = ShadowOrderBook()
        self.pending: List[Order] = []

    def process_new_order(self, order: Order, exchtime_arrive: float) -> List[Event]:
        order.exchtime_arrive = exchtime_arrive
        events: List[Event] = []
        if not self._is_active(order.side, order.px, exchtime_arrive):
            self.pending.append(order)
            return events

        self._activate_order(order, exchtime_arrive)
        events.extend(self._handle_arrival_fill(order, exchtime_arrive))
        return events

    def process_cancel(self, order_id: str, exchtime_arrive: float) -> Event:
        order = self.book.get(order_id)
        if not order or order.status in {OrderStatus.FILLED, OrderStatus.CANCELED}:
            return Event(time=exchtime_arrive, event_type=EventType.CANCEL_ACK_RECV, order_id=order_id, status="REJECTED")
        filled_qty = self._fill_to_time(order, exchtime_arrive)
        order.filled_qty = filled_qty
        order.status = OrderStatus.CANCELED
        return Event(time=exchtime_arrive, event_type=EventType.CANCEL_ACK_RECV, order_id=order_id, status="CANCELED")

    def advance_time(self, exchtime: float) -> List[Event]:
        events: List[Event] = []
        self._activate_pending(exchtime)
        for order in list(self.book.live_orders()):
            events.extend(self._handle_fill_progress(order, exchtime))
        return events

    def _activate_pending(self, exchtime: float) -> None:
        remaining = []
        for order in self.pending:
            if self._is_active(order.side, order.px, exchtime):
                self._activate_order(order, exchtime)
            else:
                remaining.append(order)
        self.pending = remaining

    def _activate_order(self, order: Order, exchtime: float) -> None:
        side = "bid" if order.side == OrderSide.BUY else "ask"
        tail = self.tape.x_at(side, order.px, exchtime) + self.tape.q_at(side, order.px, exchtime)
        shadow = self.book.shadow_remaining(order.side, order.px)
        order.pos = tail + shadow
        self.book.add(order)

    def _handle_arrival_fill(self, order: Order, exchtime: float) -> List[Event]:
        fill_qty = self._fill_to_time(order, exchtime)
        order.filled_qty = fill_qty
        if order.filled_qty >= order.qty:
            order.status = OrderStatus.FILLED
            return self._build_fill_events(order, exchtime, fill_qty)
        if order.tif == TimeInForce.IOC:
            order.status = OrderStatus.CANCELED
            return [Event(time=exchtime, event_type=EventType.CANCEL_ACK_RECV, order_id=order.order_id, status="IOC_CANCEL")]
        if order.filled_qty > 0:
            order.status = OrderStatus.PARTIAL
        return []

    def _handle_fill_progress(self, order: Order, exchtime: float) -> List[Event]:
        if order.status not in {OrderStatus.LIVE, OrderStatus.PARTIAL}:
            return []
        fill_qty = self._fill_to_time(order, exchtime)
        if fill_qty <= order.filled_qty:
            return []
        order.filled_qty = fill_qty
        if order.filled_qty >= order.qty:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIAL
        return self._build_fill_events(order, exchtime, fill_qty)

    def _fill_to_time(self, order: Order, exchtime: float) -> float:
        if order.pos is None:
            return order.filled_qty
        side = "bid" if order.side == OrderSide.BUY else "ask"
        return min(order.qty, max(0.0, self.tape.x_at(side, order.px, exchtime) - order.pos))

    def _build_fill_events(self, order: Order, exchtime: float, filled_qty: float) -> List[Event]:
        if filled_qty <= 0:
            return []
        recv_fill = self.mapper.recv_from_exch(exchtime)
        recv_recv = recv_fill + self.config.delay_in
        fill = Fill(qty=filled_qty, px=order.px, exchtime=exchtime, recvtime=recv_recv)
        order.fills.append(fill)
        return [
            Event(
                time=recv_recv,
                event_type=EventType.EXEC_REPORT_RECV,
                order_id=order.order_id,
                fill_qty=filled_qty,
                fill_px=order.px,
                exchtime=exchtime,
                recvtime=recv_recv,
                status=order.status.value,
            )
        ]

    def _is_active(self, side: OrderSide, price: float, exchtime: float) -> bool:
        tape_side = "bid" if side == OrderSide.BUY else "ask"
        return price in self.tape.active_prices(tape_side, exchtime)
