from dataclasses import dataclass


@dataclass(frozen=True)
class TimeMapper:
    """Linear mapping between exchange and strategy time."""

    a: float
    b: float

    def recv_from_exch(self, exchtime: float) -> float:
        return self.a * exchtime + self.b

    def exch_from_recv(self, recvtime: float) -> float:
        return (recvtime - self.b) / self.a
