from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from .config import SimulationConfig
from .events import Event, EventType
from .exchange import ExchangeSimulator
from .orders import Order
from .strategy import Strategy
from .tape import EventTape, Snapshot, build_event_tape
from .time import TimeMapper


@dataclass
class IntervalInput:
    snapshot_a: Snapshot
    snapshot_b: Snapshot
    lastvolsplit: List[tuple[float, float]]
    tick_size: float


class BacktestEngine:
    def __init__(self, config: SimulationConfig, strategy: Strategy) -> None:
        self.config = config
        self.strategy = strategy
        self.mapper = TimeMapper(config.a, config.b)

    def run_interval(self, interval: IntervalInput) -> List[Event]:
        self.config.validate()
        tape = build_event_tape(
            interval.snapshot_a,
            interval.snapshot_b,
            interval.lastvolsplit,
            interval.tick_size,
            self.config.epsilon,
            self.config.lambda_,
            self.config.phi,
        )
        exchange = ExchangeSimulator(tape, self.config, self.mapper)
        events: List[Event] = []
        prev_recv = self.mapper.recv_from_exch(interval.snapshot_a.time)
        events.append(Event(time=prev_recv, event_type=EventType.SNAPSHOT_RECV))
        for order in self.strategy.on_snapshot(interval.snapshot_a, prev_recv):
            events.extend(self._handle_new_order(order, exchange))

        events.extend(self._run_exchange_loop(exchange, tape, interval.snapshot_b.time))
        return events

    def _handle_new_order(self, order: Order, exchange: ExchangeSimulator) -> List[Event]:
        recv_arr = order.recv_send_time + self.config.delay_out
        exchtime_arr = self.mapper.exch_from_recv(recv_arr)
        return exchange.process_new_order(order, exchtime_arr)

    def _run_exchange_loop(self, exchange: ExchangeSimulator, tape: EventTape, t_end: float) -> List[Event]:
        events: List[Event] = []
        for segment in tape.segments:
            if segment.t_start >= t_end:
                break
            events.extend(exchange.advance_time(min(segment.t_end, t_end)))
        events.append(Event(time=t_end, event_type=EventType.INTERVAL_END))
        return events
