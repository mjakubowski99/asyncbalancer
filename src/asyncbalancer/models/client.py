from dataclasses import dataclass, field

@dataclass
class Preference:
    key: str 
    weight: int

@dataclass
class ProviderRequest:
    preferences: list[Preference] = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)
    tier: str | None = None

@dataclass 
class ProviderResponse:
    success: bool
    data: dict 
    latency: int 
    error: str | None