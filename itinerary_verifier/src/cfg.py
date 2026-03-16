import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Cfg:
    endpoint_port: int

    @classmethod
    def from_env(cls) -> "Cfg":
        return cls(endpoint_port=int(os.getenv("PORT", "8080")))
