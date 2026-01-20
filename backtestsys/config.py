from dataclasses import dataclass


@dataclass(frozen=True)
class SimulationConfig:
    """Configuration for time mapping and tape construction."""

    a: float
    b: float
    delay_out: float = 0.0
    delay_in: float = 0.0
    epsilon: float = 1e-6
    lambda_: float = 0.0
    phi: float = 0.0

    def validate(self) -> None:
        if self.a <= 0:
            raise ValueError("Parameter a must be positive for a monotone time mapping.")
        if self.epsilon <= 0:
            raise ValueError("epsilon must be positive.")
        if not 0.0 <= self.phi <= 1.0:
            raise ValueError("phi must be in [0, 1].")
