from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from .orders import Order
from .tape import Snapshot


class Strategy(ABC):
    @abstractmethod
    def on_snapshot(self, snapshot: Snapshot, recvtime: float) -> Iterable[Order]:
        """Handle snapshot receipt and return orders to send."""
        raise NotImplementedError
