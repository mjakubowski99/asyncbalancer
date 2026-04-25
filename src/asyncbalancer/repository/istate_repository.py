from abc import ABC, abstractmethod

from asyncbalancer.models.state import ProviderState

class IStateRepository(ABC):
    @abstractmethod
    async def lock(self, key: str) -> bool:
        pass

    @abstractmethod
    async def unlock(self, key: str) -> bool:
        pass

    @abstractmethod
    async def get_state(self, key: str) -> ProviderState:
        pass

    @abstractmethod
    async def get_states(self, keys: list[str]) -> list[ProviderState]:
        pass

    @abstractmethod
    async def remove_state(self, key: str) -> bool:
        pass

    @abstractmethod
    async def save_state(self, state: ProviderState) -> bool:
        pass

    @abstractmethod
    async def get_with_lowest_score(self, limit: int = 5) -> list[str]:
        pass