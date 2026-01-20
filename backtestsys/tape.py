from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PriceQty = Tuple[float, float]


@dataclass(frozen=True)
class Snapshot:
    time: float
    bids: Sequence[PriceQty]
    asks: Sequence[PriceQty]

    def top_price(self, side: str) -> float:
        book = self.bids if side == "bid" else self.asks
        if not book:
            raise ValueError("Snapshot side is empty")
        return book[0][0]

    def qty_map(self, side: str) -> Dict[float, float]:
        book = self.bids if side == "bid" else self.asks
        return {price: qty for price, qty in book}


@dataclass(frozen=True)
class SegmentFlows:
    trade: float
    net: float
    cancel: float
    start_q: float
    start_x: float
    dt: float

    def q_at(self, z: float) -> float:
        return max(0.0, self.start_q + self.net * z - self.trade * z)

    def x_at(self, z: float, phi: float) -> float:
        return self.start_x + (self.trade + phi * self.cancel) * z


@dataclass(frozen=True)
class Segment:
    t_start: float
    t_end: float
    best_bid: float
    best_ask: float
    active_bids: Tuple[float, ...]
    active_asks: Tuple[float, ...]
    flows_bid: Dict[float, SegmentFlows]
    flows_ask: Dict[float, SegmentFlows]

    @property
    def dt(self) -> float:
        return self.t_end - self.t_start


@dataclass
class EventTape:
    segments: List[Segment]
    tick_size: float
    phi: float

    def segment_index(self, exchtime: float) -> int:
        for idx, segment in enumerate(self.segments):
            if segment.t_start <= exchtime < segment.t_end:
                return idx
        return max(0, len(self.segments) - 1)

    def active_prices(self, side: str, exchtime: float) -> Iterable[float]:
        segment = self.segments[self.segment_index(exchtime)]
        return segment.active_bids if side == "bid" else segment.active_asks

    def x_at(self, side: str, price: float, exchtime: float) -> float:
        idx = self.segment_index(exchtime)
        segment = self.segments[idx]
        flows = segment.flows_bid if side == "bid" else segment.flows_ask
        flow = flows.get(price)
        if not flow:
            return 0.0
        z = (exchtime - segment.t_start) / segment.dt if segment.dt > 0 else 0.0
        return flow.x_at(z, self.phi)

    def q_at(self, side: str, price: float, exchtime: float) -> float:
        idx = self.segment_index(exchtime)
        segment = self.segments[idx]
        flows = segment.flows_bid if side == "bid" else segment.flows_ask
        flow = flows.get(price)
        if not flow:
            return 0.0
        z = (exchtime - segment.t_start) / segment.dt if segment.dt > 0 else 0.0
        return flow.q_at(z)

    def next_fill_time(
        self,
        side: str,
        price: float,
        start_time: float,
        target_x: float,
    ) -> Optional[float]:
        idx = self.segment_index(start_time)
        for segment in self.segments[idx:]:
            flows = segment.flows_bid if side == "bid" else segment.flows_ask
            flow = flows.get(price)
            if not flow:
                continue
            start_z = 0.0
            if segment.t_start <= start_time < segment.t_end:
                start_z = (start_time - segment.t_start) / segment.dt if segment.dt > 0 else 0.0
            x_start = flow.x_at(start_z, self.phi)
            x_end = flow.x_at(1.0, self.phi)
            if x_start >= target_x:
                return start_time
            if x_end >= target_x:
                rate = (flow.trade + self.phi * flow.cancel) / segment.dt if segment.dt > 0 else 0.0
                if rate <= 0:
                    continue
                return segment.t_start + (target_x - flow.start_x) / rate
        return None


def build_event_tape(
    snapshot_a: Snapshot,
    snapshot_b: Snapshot,
    lastvolsplit: Sequence[PriceQty],
    tick_size: float,
    epsilon: float,
    lambda_: float,
    phi: float,
) -> EventTape:
    best_path_bid = _build_best_path(snapshot_a.top_price("bid"), snapshot_b.top_price("bid"), lastvolsplit, tick_size)
    best_path_ask = _build_best_path(snapshot_a.top_price("ask"), snapshot_b.top_price("ask"), lastvolsplit, tick_size)
    segments_price = _merge_paths(best_path_bid, best_path_ask)

    widths = _allocate_segment_widths(segments_price, lastvolsplit, epsilon)
    t_bounds = _map_to_time(snapshot_a.time, snapshot_b.time, widths, lambda_)

    active_by_segment = [
        (
            tuple(segments_price[i][0] - k * tick_size for k in range(5)),
            tuple(segments_price[i][1] + k * tick_size for k in range(5)),
        )
        for i in range(len(segments_price))
    ]

    segment_dts = [t_bounds[i + 1] - t_bounds[i] for i in range(len(segments_price))]
    flows_bid, flows_ask = _build_flows(
        segments_price,
        active_by_segment,
        segment_dts,
        snapshot_a,
        snapshot_b,
        lastvolsplit,
        phi,
    )

    segments = []
    for i, (best_bid, best_ask) in enumerate(segments_price):
        segments.append(
            Segment(
                t_start=t_bounds[i],
                t_end=t_bounds[i + 1],
                best_bid=best_bid,
                best_ask=best_ask,
                active_bids=active_by_segment[i][0],
                active_asks=active_by_segment[i][1],
                flows_bid=flows_bid[i],
                flows_ask=flows_ask[i],
            )
        )

    return EventTape(segments=segments, tick_size=tick_size, phi=phi)


def _build_best_path(
    price_a: float,
    price_b: float,
    lastvolsplit: Sequence[PriceQty],
    tick_size: float,
) -> List[float]:
    prices = [price for price, qty in lastvolsplit if qty > 0]
    if not prices:
        return [price_a, price_b]
    p_min, p_max = min(prices), max(prices)
    dist_a = abs(price_a - p_min) + abs(p_min - p_max) + abs(p_max - price_b)
    dist_b = abs(price_a - p_max) + abs(p_max - p_min) + abs(p_min - price_b)
    if dist_a <= dist_b:
        path = [price_a, p_min, p_max, price_b]
    else:
        path = [price_a, p_max, p_min, price_b]
    expanded: List[float] = []
    for start, end in zip(path[:-1], path[1:]):
        expanded.extend(_expand_segment(start, end, tick_size))
    if expanded and expanded[-1] != price_b:
        expanded.append(price_b)
    return expanded or [price_a, price_b]


def _expand_segment(start: float, end: float, tick_size: float) -> List[float]:
    if start == end:
        return [start]
    step = tick_size if end > start else -tick_size
    count = int(round((end - start) / step))
    return [start + step * i for i in range(count + 1)]


def _merge_paths(path_bid: Sequence[float], path_ask: Sequence[float]) -> List[Tuple[float, float]]:
    max_len = max(len(path_bid), len(path_ask))
    merged: List[Tuple[float, float]] = []
    bid = path_bid[0]
    ask = path_ask[0]
    for idx in range(max_len):
        if idx < len(path_bid):
            bid = path_bid[idx]
        if idx < len(path_ask):
            ask = path_ask[idx]
        if not merged or merged[-1] != (bid, ask):
            merged.append((bid, ask))
    return merged


def _allocate_segment_widths(
    segments_price: Sequence[Tuple[float, float]],
    lastvolsplit: Sequence[PriceQty],
    epsilon: float,
) -> List[float]:
    n = len(segments_price)
    widths = [1.0 / n for _ in range(n)]
    for _ in range(2):
        m_bid = _allocate_trades(segments_price, lastvolsplit, widths, side="bid")
        m_ask = _allocate_trades(segments_price, lastvolsplit, widths, side="ask")
        e = [m_bid[i] + m_ask[i] for i in range(n)]
        weights = [epsilon + value for value in e]
        total = sum(weights)
        widths = [w / total for w in weights]
    return widths


def _allocate_trades(
    segments_price: Sequence[Tuple[float, float]],
    lastvolsplit: Sequence[PriceQty],
    widths: Sequence[float],
    side: str,
) -> List[float]:
    n = len(segments_price)
    m = [0.0 for _ in range(n)]
    for price, qty in lastvolsplit:
        visits = [i for i, (bid, ask) in enumerate(segments_price) if (bid if side == "bid" else ask) == price]
        if not visits:
            continue
        total_w = sum(widths[i] for i in visits)
        for i in visits:
            m[i] += qty * (widths[i] / total_w)
    return m


def _map_to_time(start: float, end: float, widths: Sequence[float], lambda_: float) -> List[float]:
    u_prime = [0.0]
    cumulative = 0.0
    for w in widths:
        cumulative += w
        u_prime.append(cumulative)

    def u_from_u_prime(value: float) -> float:
        if abs(lambda_) < 1e-6:
            return value
        return -(1.0 / lambda_) * math.log(1 - (1 - math.exp(-lambda_)) * value)

    u = [u_from_u_prime(val) for val in u_prime]
    return [start + (end - start) * val for val in u]


def _build_flows(
    segments_price: Sequence[Tuple[float, float]],
    active_by_segment: Sequence[Tuple[Tuple[float, ...], Tuple[float, ...]]],
    segment_dts: Sequence[float],
    snapshot_a: Snapshot,
    snapshot_b: Snapshot,
    lastvolsplit: Sequence[PriceQty],
    phi: float,
) -> Tuple[List[Dict[float, SegmentFlows]], List[Dict[float, SegmentFlows]]]:
    bid_universe = {price for segment in active_by_segment for price in segment[0]}
    ask_universe = {price for segment in active_by_segment for price in segment[1]}

    bid_flows = _build_side_flows(
        "bid",
        bid_universe,
        segments_price,
        active_by_segment,
        segment_dts,
        snapshot_a,
        snapshot_b,
        lastvolsplit,
        phi,
    )
    ask_flows = _build_side_flows(
        "ask",
        ask_universe,
        segments_price,
        active_by_segment,
        segment_dts,
        snapshot_a,
        snapshot_b,
        lastvolsplit,
        phi,
    )
    return bid_flows, ask_flows


def _build_side_flows(
    side: str,
    universe: Iterable[float],
    segments_price: Sequence[Tuple[float, float]],
    active_by_segment: Sequence[Tuple[Tuple[float, ...], Tuple[float, ...]]],
    segment_dts: Sequence[float],
    snapshot_a: Snapshot,
    snapshot_b: Snapshot,
    lastvolsplit: Sequence[PriceQty],
    phi: float,
) -> List[Dict[float, SegmentFlows]]:
    n = len(segments_price)
    m_per_segment = _allocate_trade_per_segment(segments_price, lastvolsplit, side)

    qty_a = snapshot_a.qty_map(side)
    qty_b = snapshot_b.qty_map(side)

    flows: List[Dict[float, SegmentFlows]] = [dict() for _ in range(n)]
    for price in universe:
        total_trade = sum(m_per_segment[i].get(price, 0.0) for i in range(n))
        delta_q = qty_b.get(price, 0.0) - qty_a.get(price, 0.0)
        net = delta_q + total_trade
        eligible = [i for i in range(n) if price in (active_by_segment[i][0] if side == "bid" else active_by_segment[i][1])]
        if not eligible:
            continue
        total_dt = sum(segment_dts[i] for i in eligible)
        running_q = qty_a.get(price, 0.0)
        running_x = 0.0
        for i in range(n):
            if i in eligible and total_dt > 0:
                net_i = net * (segment_dts[i] / total_dt)
            else:
                net_i = 0.0
            trade_i = m_per_segment[i].get(price, 0.0)
            cancel_i = max(-net_i, 0.0)
            flows[i][price] = SegmentFlows(
                trade=trade_i,
                net=net_i,
                cancel=cancel_i,
                start_q=running_q,
                start_x=running_x,
                dt=segment_dts[i],
            )
            running_q = max(0.0, running_q + net_i - trade_i)
            running_x += trade_i + phi * cancel_i
    return flows


def _allocate_trade_per_segment(
    segments_price: Sequence[Tuple[float, float]],
    lastvolsplit: Sequence[PriceQty],
    side: str,
) -> List[Dict[float, float]]:
    n = len(segments_price)
    widths = [1.0 / n for _ in range(n)]
    m_segments: List[Dict[float, float]] = [dict() for _ in range(n)]
    for price, qty in lastvolsplit:
        visits = [i for i, (bid, ask) in enumerate(segments_price) if (bid if side == "bid" else ask) == price]
        if not visits:
            continue
        total_w = sum(widths[i] for i in visits)
        for i in visits:
            alloc = qty * (widths[i] / total_w)
            m_segments[i][price] = m_segments[i].get(price, 0.0) + alloc
    return m_segments
